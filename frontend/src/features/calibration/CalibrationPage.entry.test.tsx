import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { SIGNED_IN } from "../../test-utils";
import { apiErrorBody, respond } from "../test-api";
import { BASE, body, button, enter, only, open, P, PRINT_SESSION, resetBetweenTests, stored, throws } from "./CalibrationPage.kit";

vi.setConfig({ testTimeout: 15_000 });
resetBetweenTests();

describe("step 2: direct entry", () => {
  it("starts from the stored values and states what the signs mean", async () => {
    await open();
    expect(await screen.findByRole("textbox", { name: "Offset X (mm)" })).toHaveValue("0.4");
    expect(screen.getByRole("textbox", { name: "Offset Y (mm)" })).toHaveValue("-0.2");
    expect(screen.getByRole("textbox", { name: "Scale X" })).toHaveValue("1.001");
    expect(screen.getByRole("textbox", { name: "Rotation (°)" })).toHaveValue("0.05");
    const text = document.body.textContent ?? "";
    expect(text).toContain("+ = printed too far right");
    expect(text).toContain("+ = printed too low");
    expect(text).toContain("above 1 = printed too large");
    expect(text).toContain("+ = rotated clockwise");
    expect(text).toContain("Enter what the printer did wrong; the hub applies the opposite itself.");
  });

  it("a tray with no correction starts at the identity", async () => {
    await open({}, SIGNED_IN, `/calibration?printer=${P}&tray=bypass`);
    expect(await screen.findByRole("textbox", { name: "Offset X (mm)" })).toHaveValue("0");
    expect(screen.getByRole("textbox", { name: "Scale X" })).toHaveValue("1");
  });

  it("saves the typed values (decimal comma accepted) with the type and version they were measured on", async () => {
    const { calls } = await open({ [`PUT ${BASE}/main`]: { ...stored, offset_x_mm: 1.4 } });
    await enter("Offset X (mm)", "1,4");
    await userEvent.click(await button("Save for this printer and tray"));
    expect(await screen.findByText("Saved. New prints use this correction.")).toBeVisible();
    expect(body(only(calls, "PUT")[0])).toEqual({
      offset_x_mm: 1.4,
      offset_y_mm: -0.2,
      scale_x: 1.001,
      scale_y: 1,
      rotation_deg: 0.05,
      measured_on: { type_key: "L4736REV", version: 1 },
    });
  });

  it("a value that is not a number blocks the save and names the field", async () => {
    const { calls } = await open();
    await enter("Scale Y", "abc");
    await userEvent.click(await button("Save for this printer and tray"));
    expect(await screen.findByText("Scale Y is not a number.")).toBeVisible();
    expect(only(calls, "PUT")).toHaveLength(0);
  });

  it("names the field and the range the server refused", async () => {
    await open({
      [`PUT ${BASE}/main`]: () =>
        respond(422, apiErrorBody("calibration_out_of_range", "Out of range.", { field: "scale_x", min: 0.95, max: 1.05, reason: "out_of_range" })),
    });
    await enter("Scale X", "1,2");
    await userEvent.click(await button("Save for this printer and tray"));
    expect(await screen.findByText("Scale X must stay between 0.95 and 1.05. More than that is a fault of the printer, not something to correct.")).toBeVisible();
  });

  it("names a value with too many decimals", async () => {
    await open({
      [`PUT ${BASE}/main`]: () =>
        respond(422, apiErrorBody("calibration_out_of_range", "Too many decimals.", { field: "offset_x_mm", min: -10, max: 10, reason: "too_many_decimals" })),
    });
    await enter("Offset X (mm)", "0,123");
    await userEvent.click(await button("Save for this printer and tray"));
    expect(await screen.findByText("Offset X has too many decimals.")).toBeVisible();
  });

  it("says in words when the server cannot be reached while saving", async () => {
    await open({ [`PUT ${BASE}/main`]: throws });
    await userEvent.click(await button("Save for this printer and tray"));
    expect(await screen.findByText("The server cannot be reached.")).toBeVisible();
    expect(screen.queryByText("Saved. New prints use this correction.")).toBeNull();
  });

  it("is disabled for a key that is not an admin, and says why", async () => {
    await open({}, PRINT_SESSION);
    expect(await button("Save for this printer and tray")).toBeDisabled();
    expect(screen.getByText("Saving needs an admin key, because it changes every print on this tray.")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Reset to no correction" })).toBeNull();
  });
});

describe("reset to no correction (N7)", () => {
  it("asks first, then deletes the tray's calibration", async () => {
    const { calls } = await open({ [`DELETE ${BASE}/main`]: null });
    await userEvent.click(await button("Reset to no correction"));
    expect(only(calls, "DELETE")).toHaveLength(0);
    expect(screen.getByText("Remove the correction of Main tray on Office laser? Prints on this tray are then not corrected.")).toBeVisible();
    await userEvent.click(await button("Yes, reset"));
    expect(await screen.findByText("Reset. This tray prints without correction.")).toBeVisible();
    expect(only(calls, "DELETE")).toHaveLength(1);
  });

  it("Cancel leaves the calibration alone", async () => {
    const { calls } = await open();
    await userEvent.click(await button("Reset to no correction"));
    await userEvent.click(await button("Cancel"));
    expect(only(calls, "DELETE")).toHaveLength(0);
    expect(screen.queryByText(/Remove the correction of/)).toBeNull();
  });

  it("says in words what the server refused", async () => {
    await open({ [`DELETE ${BASE}/main`]: () => respond(422, apiErrorBody("tray_unknown", "No such tray.")) });
    await userEvent.click(await button("Reset to no correction"));
    await userEvent.click(await button("Yes, reset"));
    expect(await screen.findByText("The printer does not report that tray.")).toBeVisible();
    expect(screen.queryByText("Reset. This tray prints without correction.")).toBeNull();
  });

  it("says in words when the server cannot be reached", async () => {
    await open({ [`DELETE ${BASE}/main`]: throws });
    await userEvent.click(await button("Reset to no correction"));
    await userEvent.click(await button("Yes, reset"));
    expect(await screen.findByText("The server cannot be reached.")).toBeVisible();
  });

  it("is not offered for a tray without a stored correction", async () => {
    await open({}, SIGNED_IN, `/calibration?printer=${P}&tray=bypass`);
    await screen.findByRole("textbox", { name: "Offset X (mm)" });
    expect(screen.queryByRole("button", { name: "Reset to no correction" })).toBeNull();
  });
});
