import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { renderApp, SIGNED_IN } from "../../test-utils";
import { apiErrorBody, mockApi, PRINTER_A, respond, SHEET_TYPE, status } from "../test-api";
import { BASE, body, button, JOB, only, open, P, READ_SESSION, resetBetweenTests, routes, secondPrinter, throws } from "./CalibrationPage.kit";

vi.setConfig({ testTimeout: 15_000 });
resetBetweenTests();

describe("the page and its preselection (C10)", () => {
  it("preselects the printer and the tray from the address, and shows the stored values with the date of the change", async () => {
    await open();
    expect(await screen.findByRole("button", { name: /Printer$/ })).toHaveTextContent("Office laser");
    expect(screen.getByRole("button", { name: /Tray$/ })).toHaveTextContent("Main tray");
    const current = await screen.findByRole("region", { name: "Current values" });
    expect(within(current).getByText("0.4 mm")).toBeVisible();
    expect(within(current).getByText("-0.2 mm")).toBeVisible();
    expect(within(current).getByText("0.05°")).toBeVisible();
    expect(within(current).getByText(/Last changed/)).toBeVisible();
    expect(within(current).getByText(/Nov 4, 2026/)).toBeVisible();
  });

  it("preselects the second printer when the address names it, not the first one", async () => {
    await open({}, SIGNED_IN, `/calibration?printer=${secondPrinter.id}&tray=main`);
    expect(await screen.findByRole("button", { name: /Printer$/ })).toHaveTextContent("Second laser");
  });

  it("preselects the tray the address names, not the default one", async () => {
    await open({}, SIGNED_IN, `/calibration?printer=${P}&tray=bypass`);
    expect(await screen.findByRole("button", { name: /Tray$/ })).toHaveTextContent("Bypass");
  });

  it("a tray without calibration says so", async () => {
    await open({}, SIGNED_IN, `/calibration?printer=${P}&tray=bypass`);
    const current = await screen.findByRole("region", { name: "Current values" });
    expect(await within(current).findByText("No correction stored for this tray.")).toBeVisible();
  });

  it("offers only enabled page printers", async () => {
    await open();
    await userEvent.click(await screen.findByRole("button", { name: /Printer$/ }));
    const names = (await screen.findAllByRole("option")).map((o) => o.textContent);
    expect(names).toEqual(["Office laser", "Second laser"]);
  });

  it("choosing another printer changes the address and takes its first tray", async () => {
    const { router } = await open();
    await userEvent.click(await screen.findByRole("button", { name: /Printer$/ }));
    await userEvent.click(await screen.findByRole("option", { name: "Second laser" }));
    await waitFor(() => expect(router.state.location.search).toMatchObject({ printer: secondPrinter.id, tray: "main" }));
  });

  it("a tray the printer does not have falls back to its default tray", async () => {
    await open({}, SIGNED_IN, `/calibration?printer=${P}&tray=gone`);
    expect(await screen.findByRole("button", { name: /Tray$/ })).toHaveTextContent("Main tray");
  });

  it("with no page printer it says what to do, and offers nothing to print", async () => {
    mockApi({ "GET /api/v1/printers": [PRINTER_A], [`GET /api/v1/printers/${PRINTER_A.id}/status`]: status(PRINTER_A.id), "GET /api/v1/sheet-types": [SHEET_TYPE] });
    await renderApp({ path: "/calibration" });
    expect(await screen.findByText("There is no page printer yet. Add one under Settings › Printers.")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Print calibration page" })).toBeNull();
  });

  it("shows the printer's state", async () => {
    await open();
    expect(await screen.findByText("Ready")).toBeVisible();
  });
});

describe("step 1: the calibration page", () => {
  it("offers only types with two columns and two rows", async () => {
    await open();
    await userEvent.click(await screen.findByRole("button", { name: /Sheet type/ }));
    const options = (await screen.findAllByRole("option")).map((o) => o.textContent ?? "");
    expect(options).toHaveLength(1);
    expect(options[0]).toMatch(/L4736REV/);
  });

  it("draws the page with its legend: black only, S and Z numbers, scales, rulers", async () => {
    await open();
    const drawing = await screen.findByRole("img", { name: /Calibration page of/ });
    expect(drawing).toBeVisible();
    const legend = screen.getByRole("list", { name: "Legend" });
    expect(legend).toHaveTextContent("S1, S2 … number the gaps between columns");
    expect(legend).toHaveTextContent("Z1, Z2 … number the gaps between rows");
    expect(legend).toHaveTextContent("black only");
    expect(legend).toHaveTextContent("checkerboard");
  });

  it("explains a gap crossing in words, with the signs", async () => {
    await open();
    const example = await screen.findByRole("region", { name: "Gap crossing S2 · Z6" });
    expect(example).toHaveTextContent("Across: + = the ink lies to the right of the middle of the gap");
    expect(example).toHaveTextContent("Down: + = the ink lies below the middle of the gap");
  });

  it("the download link ends in /page/pdf and names the type, its version and no correction", async () => {
    await open();
    const link = await screen.findByRole("link", { name: "Download PDF" });
    const [path, query] = link.getAttribute("href")!.split("?");
    expect(path).toBe(`${BASE}/main/page/pdf`);
    expect(path!.endsWith("/page/pdf")).toBe(true);
    expect(new URLSearchParams(query).get("type")).toBe("L4736REV");
    expect(new URLSearchParams(query).get("corrected")).toBe("false");
  });

  it("a key that may not use the printer is told so in words, and there is no PDF link to a JSON error", async () => {
    mockApi(routes({ [`GET ${BASE}`]: respond(403, apiErrorBody("printer_not_allowed", "no")) }));
    await renderApp({ path: `/calibration?printer=${P}&tray=main`, session: SIGNED_IN });
    expect(await screen.findByText("This key may not use this printer.")).toBeVisible();
    expect(screen.queryByRole("link", { name: "Download PDF" })).toBeNull();
  });

  it("prints the calibration page without correction and links to the job", async () => {
    const { calls } = await open({ [`POST ${BASE}/main/page`]: respond(202, { job_id: JOB }) });
    await userEvent.click(await button("Print calibration page"));
    expect(await within(await screen.findByRole("status", { name: "Calibration page status" })).findByText("Queued")).toBeVisible();
    expect(body(only(calls, "POST", "/page")[0])).toEqual({ type: "L4736REV", version: 1, corrected: false });
    expect(screen.getByRole("link", { name: "Show the job" })).toHaveAttribute("href", `/jobs/${JOB}`);
  });

  it("says in words when the print queue does not know the printer (printer-unavailable)", async () => {
    await open({
      [`POST ${BASE}/main/page`]: () =>
        respond(409, { detail: { type: "printer-unavailable", title: "Printer is not available to the print queue", status: 409, detail: "Printer is not known" } }),
    });
    await userEvent.click(await button("Print calibration page"));
    expect(await screen.findByText("The print queue does not know this printer yet. Try again in a moment.")).toBeVisible();
    expect(screen.queryByRole("link", { name: "Show the job" })).toBeNull();
  });

  it("says in words when the printer is held after a device swap (printer-identity-mismatch)", async () => {
    await open({
      [`POST ${BASE}/main/page`]: () =>
        respond(409, { detail: { type: "printer-identity-mismatch", title: "Held", status: 409, detail: "The printer is held" } }),
    });
    await userEvent.click(await button("Print calibration page"));
    expect(
      await screen.findByText("This printer may be a different device now. An admin has to confirm it on the printer's page first."),
    ).toBeVisible();
  });

  it("says in words when the sheet type has no crossings", async () => {
    await open({ [`POST ${BASE}/main/page`]: () => respond(422, apiErrorBody("calibration_type_unsuitable", "No crossings.", { cols: 1, rows: 4 })) });
    await userEvent.click(await button("Print calibration page"));
    expect(await screen.findByText("This sheet type has fewer than two columns or two rows, so its calibration page has no crossings.")).toBeVisible();
  });

  it("says in words when the server cannot be reached", async () => {
    await open({ [`POST ${BASE}/main/page`]: throws });
    await userEvent.click(await button("Print calibration page"));
    expect(await screen.findByText("The server cannot be reached.")).toBeVisible();
  });

  it("a key that may only read cannot print", async () => {
    await open({}, READ_SESSION);
    expect(await button("Print calibration page")).toBeDisabled();
  });
});

describe("print without a print key", () => {
  it("says why the print buttons are disabled", async () => {
    await open({}, READ_SESSION);
    expect(await button("Print calibration page")).toBeDisabled();
    expect((await screen.findAllByText("Printing needs a print or admin key.")).length).toBeGreaterThan(0);
  });
});

describe("step 3: check print with correction", () => {
  it("prints the page with the stored correction", async () => {
    const { calls } = await open({ [`POST ${BASE}/main/page`]: respond(202, { job_id: JOB }) });
    await userEvent.click(await button("Check print with correction"));
    expect(await within(await screen.findByRole("status", { name: "Check page status" })).findByText("Queued")).toBeVisible();
    expect(body(only(calls, "POST", "/page")[0])).toEqual({ type: "L4736REV", version: 1, corrected: true });
    expect(screen.getByText(/within 0\.5 mm/)).toBeVisible();
  });

  it("says in words when the print queue does not know the printer", async () => {
    await open({ [`POST ${BASE}/main/page`]: () => respond(409, { detail: { type: "printer-unavailable", title: "x", status: 409, detail: "y" } }) });
    await userEvent.click(await button("Check print with correction"));
    expect(await screen.findByText("The print queue does not know this printer yet. Try again in a moment.")).toBeVisible();
  });

  it("says in words when the server cannot be reached", async () => {
    await open({ [`POST ${BASE}/main/page`]: throws });
    await userEvent.click(await button("Check print with correction"));
    expect(await screen.findByText("The server cannot be reached.")).toBeVisible();
  });

  it("is not offered while the tray has no correction", async () => {
    await open({}, SIGNED_IN, `/calibration?printer=${P}&tray=bypass`);
    expect(await button("Check print with correction")).toBeDisabled();
  });
});

describe("the German page", () => {
  it("is translated, with the signs in words", async () => {
    mockApi(routes());
    await renderApp({ path: `/calibration?printer=${P}&tray=main`, language: "de" });
    expect(await screen.findByRole("button", { name: "Kalibrierseite drucken" })).toBeVisible();
    expect(document.body.textContent).toContain("+ = zu weit rechts gedruckt");
  });
});
