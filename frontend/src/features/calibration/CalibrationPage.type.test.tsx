import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { SIGNED_IN } from "../../test-utils";
import { SHEET_TYPE } from "../test-api";
import { BASE, body, button, enter, fillThree, FIT, only, open, P, resetBetweenTests, secondPrinter, stored, typeB } from "./CalibrationPage.kit";

vi.setConfig({ testTimeout: 15_000 });
resetBetweenTests();

describe("the chosen sheet type lives in the address (#238)", () => {
  const two = { "GET /api/v1/sheet-types": [SHEET_TYPE, typeB] };
  const typeBox = () => screen.findByRole("combobox", { name: /Sheet type/ });
  async function chooseB() {
    await userEvent.click(await screen.findByRole("button", { name: /Sheet type/ }));
    await userEvent.click(await screen.findByRole("option", { name: /OTHERTYPE/ }));
  }

  it("type survives a tray change", async () => {
    const { router } = await open(two);
    await chooseB();
    await waitFor(() => expect(router.state.location.search).toMatchObject({ type: "OTHERTYPE" }));
    await userEvent.click(await screen.findByRole("button", { name: /Tray$/ }));
    await userEvent.click(await screen.findByRole("option", { name: "Bypass" }));
    await waitFor(() => expect(router.state.location.search).toMatchObject({ tray: "bypass", type: "OTHERTYPE" }));
    expect(((await typeBox()) as HTMLInputElement).value).toContain("OTHERTYPE");
  });

  it("type survives a printer change", async () => {
    const { router } = await open(two);
    await chooseB();
    await userEvent.click(await screen.findByRole("button", { name: /Printer$/ }));
    await userEvent.click(await screen.findByRole("option", { name: "Second laser" }));
    await waitFor(() => expect(router.state.location.search).toMatchObject({ printer: secondPrinter.id, type: "OTHERTYPE" }));
    expect(((await typeBox()) as HTMLInputElement).value).toContain("OTHERTYPE");
  });

  it("opens on the type the address names (what a reload does)", async () => {
    await open(two, SIGNED_IN, `/calibration?printer=${P}&tray=main&type=OTHERTYPE`);
    expect(((await typeBox()) as HTMLInputElement).value).toContain("OTHERTYPE");
  });

  it("an unknown or overlong type falls back to the default type", async () => {
    await open(two, SIGNED_IN, `/calibration?printer=${P}&tray=main&type=gone`);
    expect(((await typeBox()) as HTMLInputElement).value).toContain("L4736REV");
  });

  it("unknown type is dropped from the address", async () => {
    const { router } = await open(two, SIGNED_IN, `/calibration?printer=${P}&tray=main&type=gone`);
    await typeBox();
    await waitFor(() => expect(router.state.location.search.type).toBeUndefined());
    expect(router.state.location.search).toMatchObject({ printer: P, tray: "main" });
    expect(((await typeBox()) as HTMLInputElement).value).toContain("L4736REV");
  });

  it("numeric-looking type key is kept", async () => {
    const numeric = { ...typeB, key: "4736", prefix: "NN", product_codes: ["NN-1"] };
    const { router } = await open({ "GET /api/v1/sheet-types": [SHEET_TYPE, numeric] }, SIGNED_IN, `/calibration?printer=${P}&tray=main&type=4736`);
    expect(((await typeBox()) as HTMLInputElement).value).toContain("4736");
    expect(router.state.location.search.type).toBe("4736");
  });

  it("an overlong type is dropped from the address", async () => {
    const { router } = await open(two, SIGNED_IN, `/calibration?printer=${P}&tray=main&type=${"x".repeat(65)}`);
    await typeBox();
    expect(router.state.location.search.type).toBeUndefined();
  });
});

describe("which type the values were measured on", () => {
  const two = { "GET /api/v1/sheet-types": [SHEET_TYPE, typeB], [`PUT ${BASE}/main`]: stored, [`POST ${BASE}/main/fit`]: FIT };
  async function chooseB() {
    await userEvent.click(await screen.findByRole("button", { name: /Sheet type/ }));
    await userEvent.click(await screen.findByRole("option", { name: /OTHERTYPE/ }));
  }

  it("a fit made on type A is saved as measured on A, even after the type select moved to B", async () => {
    const { calls } = await open(two);
    await fillThree();
    await userEvent.click(await button("Fit"));
    await screen.findByRole("table", { name: "Result of the fit" });
    await chooseB();
    await userEvent.click(await button("Save for this printer and tray"));
    await screen.findByText("Saved. New prints use this correction.");
    expect(body(only(calls, "PUT")[0]).measured_on).toEqual({ type_key: "L4736REV", version: 1 });
  });

  it("switching the type clears the readings and the fit result", async () => {
    await open(two);
    await fillThree();
    await userEvent.click(await button("Fit"));
    await screen.findByRole("table", { name: "Result of the fit" });
    await chooseB();
    await waitFor(() => expect(screen.queryByRole("table", { name: "Result of the fit" })).toBeNull());
    expect(await screen.findByRole("textbox", { name: "Across at S1 · Z1 (mm)" })).toHaveValue("");
  });

  it("values typed by hand are saved with the type chosen at that moment", async () => {
    const { calls } = await open(two);
    await chooseB();
    await enter("Offset X (mm)", "1");
    await userEvent.click(await button("Save for this printer and tray"));
    await screen.findByText("Saved. New prints use this correction.");
    expect(body(only(calls, "PUT")[0]).measured_on).toEqual({ type_key: "OTHERTYPE", version: 3 });
  });

  it("a fitted value that is edited by hand is no longer a fit result: the current type is sent", async () => {
    const { calls } = await open(two);
    await fillThree();
    await userEvent.click(await button("Fit"));
    await screen.findByRole("table", { name: "Result of the fit" });
    await chooseB();
    await enter("Offset X (mm)", "0,3");
    await userEvent.click(await button("Save for this printer and tray"));
    await screen.findByText("Saved. New prints use this correction.");
    expect(body(only(calls, "PUT")[0]).measured_on).toEqual({ type_key: "OTHERTYPE", version: 3 });
  });
});
