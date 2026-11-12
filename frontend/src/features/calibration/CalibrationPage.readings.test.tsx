import { fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { apiErrorBody, respond } from "../test-api";
import { BASE, body, button, enter, enterAll, fillThree, FIT, only, open, resetBetweenTests, throws, twoColumns } from "./CalibrationPage.kit";

vi.setConfig({ testTimeout: 15_000 });
resetBetweenTests();

describe("step 2: the readings helper", () => {
  it("suggests the four outermost crossings of L4736REV", async () => {
    await open();
    for (const name of ["S1 · Z1", "S3 · Z1", "S1 · Z11", "S3 · Z11"]) {
      expect(await screen.findByRole("textbox", { name: `Across at ${name} (mm)` })).toBeVisible();
    }
    expect(screen.getAllByRole("group", { name: /^Reading \d/ })).toHaveLength(4);
  });

  it("keeps Fit disabled below three complete readings, and says so", async () => {
    const { calls } = await open();
    const fit = await button("Fit");
    expect(fit).toBeDisabled();
    expect(screen.getByText("Enter at least three readings to fit.")).toBeVisible();
    await enter("Across at S1 · Z1 (mm)", "0,2");
    await enter("Down at S1 · Z1 (mm)", "0");
    await enter("Across at S3 · Z1 (mm)", "0,2");
    await enter("Down at S3 · Z1 (mm)", "0");
    expect(fit).toBeDisabled();
    expect(only(calls, "POST")).toHaveLength(0);
  });

  it("fits three readings, shows the residuals, flags the far one and fills the values", async () => {
    const { calls } = await open({ [`POST ${BASE}/main/fit`]: FIT });
    await fillThree();
    await userEvent.click(await button("Fit"));
    const table = await screen.findByRole("table", { name: "Result of the fit" });
    expect(body(only(calls, "POST", "/fit")[0])).toEqual({
      type: "L4736REV",
      version: 1,
      readings: [
        { col_gap: 1, row_gap: 1, across_mm: 0.2, down_mm: -0.1 },
        { col_gap: 3, row_gap: 1, across_mm: 0.4, down_mm: 0 },
        { col_gap: 1, row_gap: 11, across_mm: 0.6, down_mm: 0.3 },
      ],
    });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows[0]).toHaveTextContent("S1 · Z1");
    expect(rows[0]).toHaveTextContent("0.05 mm");
    expect(rows[0]).not.toHaveTextContent("check this reading");
    expect(rows[1]).toHaveTextContent("S3 · Z1");
    expect(rows[1]).toHaveTextContent("0.42 mm");
    expect(rows[1]).toHaveTextContent("check this reading");
    expect(screen.getByRole("textbox", { name: "Offset X (mm)" })).toHaveValue("0.35");
    expect(screen.getByRole("textbox", { name: "Scale X" })).toHaveValue("1.0012");
    expect(screen.getByText("The values are filled in below. Nothing is saved yet.")).toBeVisible();
  });

  it("the table that scrolls sideways is a named region the keyboard can reach", async () => {
    await open({ [`POST ${BASE}/main/fit`]: FIT });
    await fillThree();
    await userEvent.click(await button("Fit"));
    const region = await screen.findByRole("region", { name: "Result of the fit" });
    expect(region).toHaveAttribute("tabindex", "0");
    expect(within(region).getByRole("table", { name: "Result of the fit" })).toBeVisible();
  });

  it("puts the flag in the cell of the residual it is about, so a phone shows it without scrolling the table sideways", async () => {
    await open({ [`POST ${BASE}/main/fit`]: FIT });
    await fillThree();
    await userEvent.click(await button("Fit"));
    const table = await screen.findByRole("table", { name: "Result of the fit" });
    expect(within(table).queryByRole("columnheader", { name: "Note" })).toBeNull();
    const flagged = within(table).getByText("check this reading");
    expect(flagged.closest("td")).toHaveTextContent("0.42 mm");
    // Not in a column of its own: the flag would sit past the edge at 360 px.
    expect(within(table).getAllByRole("columnheader")).toHaveLength(4);
  });

  it("names fitted values that are outside the allowed range, and does not fill them in", async () => {
    await open({ [`POST ${BASE}/main/fit`]: { ...FIT, values: { ...FIT.values, offset_x_mm: 14 }, out_of_range: ["offset_x_mm", "rotation_deg"] } });
    await fillThree();
    await userEvent.click(await button("Fit"));
    expect(await screen.findByText(/These fitted values are outside the allowed range: offset X \(±10 mm\), rotation \(±2°\)/)).toBeVisible();
    expect(screen.getByRole("textbox", { name: "Offset X (mm)" })).toHaveValue("0.4");
  });

  it("shows readings_insufficient in words, for each reason", async () => {
    const reasons: Record<string, string> = {
      fewer_than_three_readings: "Three readings are needed.",
      readings_on_one_line: "All readings lie on one line. Read crossings that are far apart, in both directions.",
      degenerate_fit: "These readings cannot be fitted. Check them and add crossings that are further apart.",
    };
    for (const [reason, words] of Object.entries(reasons)) {
      const view = await open({ [`POST ${BASE}/main/fit`]: () => respond(422, apiErrorBody("readings_insufficient", "Not enough.", { reason })) });
      await fillThree();
      await userEvent.click(await button("Fit"));
      expect(await screen.findByText(words)).toBeVisible();
      view.unmount();
    }
  });

  it("names the reading that points at a gap the sheet does not have", async () => {
    await open({
      [`POST ${BASE}/main/fit`]: () => respond(422, apiErrorBody("invalid_geometry", "Bad gap.", { field: "readings[2].col_gap", reason: "no such gap", reading: 2 })),
    });
    await fillThree();
    await userEvent.click(await button("Fit"));
    expect(await screen.findByText("Reading 3 names a gap that this sheet does not have.")).toBeVisible();
  });

  it("says in words when the server cannot be reached while fitting", async () => {
    await open({ [`POST ${BASE}/main/fit`]: throws });
    await fillThree();
    await userEvent.click(await button("Fit"));
    expect(await screen.findByText("The server cannot be reached.")).toBeVisible();
  });

  it("adds a reading and removes one", async () => {
    await open();
    await userEvent.click(await button("Add reading"));
    expect(screen.getAllByRole("group", { name: /^Reading \d/ })).toHaveLength(5);
    await userEvent.click(screen.getByRole("button", { name: "Remove reading 5" }));
    expect(screen.getAllByRole("group", { name: /^Reading \d/ })).toHaveLength(4);
  });
});

describe("readings: row identity", () => {
  const firstBox = (n: number) => within(screen.getByRole("group", { name: `Reading ${n}` })).getAllByRole("textbox")[0]!;

  it("rows keep distinct identities through add and remove: typing and Remove touch one row only", async () => {
    await open();
    await screen.findByRole("group", { name: "Reading 4" });
    const add = () => userEvent.click(screen.getByRole("button", { name: "Add reading" }));
    const removeFirst = () => userEvent.click(screen.getByRole("button", { name: "Remove reading 1" }));
    await removeFirst();
    await add();
    await add();
    await removeFirst();
    await removeFirst();
    await add();
    expect(screen.getAllByRole("group", { name: /^Reading \d/ })).toHaveLength(4);
    fireEvent.change(firstBox(4), { target: { value: "0,5" } });
    expect(firstBox(4)).toHaveValue("0,5");
    expect(firstBox(3)).toHaveValue("");
    expect(firstBox(2)).toHaveValue("");
    expect(firstBox(1)).toHaveValue("");
    await userEvent.click(screen.getByRole("button", { name: "Remove reading 4" }));
    expect(screen.getAllByRole("group", { name: /^Reading \d/ })).toHaveLength(3);
  });

  it("a new reading starts at a crossing that is not in the list yet", async () => {
    await open();
    await userEvent.click(await button("Add reading"));
    expect(await screen.findByRole("textbox", { name: "Across at S2 · Z1 (mm)" })).toBeVisible();
  });

  it("names the visible row when the server's reading index skips an empty row", async () => {
    await open({
      [`POST ${BASE}/main/fit`]: () => respond(422, apiErrorBody("invalid_geometry", "Bad gap.", { field: "readings[0].col_gap", reason: "no such gap", reading: 0 })),
    });
    await enterAll(
      ([["S3 · Z1", "0,4", "0"], ["S1 · Z11", "0,6", "0,3"], ["S3 · Z11", "0,1", "0,1"]] as const).flatMap(
        ([crossing, a, d]) => [[`Across at ${crossing} (mm)`, a], [`Down at ${crossing} (mm)`, d]] as const,
      ),
    );
    await userEvent.click(await button("Fit"));
    expect(await screen.findByText("Reading 2 names a gap that this sheet does not have.")).toBeVisible();
  });

  it("a sheet with two columns has no readings helper and says to enter the values directly", async () => {
    await open({ "GET /api/v1/sheet-types": [twoColumns] });
    expect(await screen.findByText("On this sheet all crossings lie on one line, so the readings cannot be fitted. Enter the values directly.")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Fit" })).toBeNull();
  });
});
