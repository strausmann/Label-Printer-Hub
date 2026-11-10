import { act, configure, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { renderApp, SIGNED_IN } from "../../test-utils";
import { recordJobEvent, resetPrintWatch } from "../jobs/printWatch";
import { apiErrorBody, GEOMETRY_L4736, job, mockApi, PAGE_CAPABILITIES, PAGE_PRINTER, pageStatus, PRINTER_A, respond, SHEET_TYPE, status, type Call } from "../test-api";

vi.setConfig({ testTimeout: 15_000 });

// Still needed after the reading rows were memoised: the page is a whole app render in jsdom
// (react-aria selects, a schematic), 60-250 ms per step, about 65 s for this file alone. With 76
// files sharing four cores in the full run the default 1 s findBy window expired on the first
// render after Fit. The window is widened for this file only and restored afterwards; the
// assertions are unchanged.
let defaultAsyncTimeout = 1000;
beforeAll(() => {
  configure((current) => {
    defaultAsyncTimeout = current.asyncUtilTimeout;
    return { asyncUtilTimeout: 5000 };
  });
});
afterAll(() => configure({ asyncUtilTimeout: defaultAsyncTimeout }));
afterEach(() => vi.unstubAllGlobals());

const P = PAGE_PRINTER.id;
const BASE = `/api/v1/printers/${P}/calibration`;
const JOB = "dddddddd-0000-4000-8000-000000000001";
const RETRY = "dddddddd-0000-4000-8000-000000000002";
const READ_SESSION = { ...SIGNED_IN, scope: "read" as const };
const PRINT_SESSION = { ...SIGNED_IN, scope: "print" as const };

const stored = {
  tray: "main",
  offset_x_mm: 0.4,
  offset_y_mm: -0.2,
  scale_x: 1.001,
  scale_y: 1,
  rotation_deg: 0.05,
  method: "manual",
  updated_at: "2026-11-04T10:00:00Z",
  measured_on: { type_key: "L4736REV", version: 1 },
};
const none = { tray: "bypass", offset_x_mm: null, offset_y_mm: null, scale_x: null, scale_y: null, rotation_deg: null, method: null, updated_at: null };
const oneColumn = { ...SHEET_TYPE, key: "ONECOL", prefix: "O1", product_codes: [], vendor: "One", geometry: { ...GEOMETRY_L4736, cols: 1 } };
const secondPrinter = { ...PAGE_PRINTER, id: "44444444-4444-4444-8444-444444444444", name: "Second laser", slug: "second" };
const typeB = { ...SHEET_TYPE, key: "OTHERTYPE", prefix: "OT", vendor: "Other", product_codes: ["OT-1"], current_version: 3 };
const twoColumns = { ...SHEET_TYPE, key: "TWOCOL", prefix: "T2", vendor: "Two", product_codes: ["T2-1"], geometry: { ...GEOMETRY_L4736, cols: 2 } };
const disabledPrinter = { ...PAGE_PRINTER, id: "55555555-5555-4555-8555-555555555555", name: "Switched off laser", enabled: false };

function routes(extra: Record<string, unknown> = {}) {
  return {
    "GET /api/v1/printers": [PAGE_PRINTER, secondPrinter, PRINTER_A, disabledPrinter],
    [`GET /api/v1/printers/${P}/status`]: pageStatus(P),
    [`GET /api/v1/printers/${secondPrinter.id}/status`]: pageStatus(secondPrinter.id),
    [`GET /api/v1/printers/${PRINTER_A.id}/status`]: status(PRINTER_A.id),
    [`GET /api/v1/printers/${P}/capabilities`]: PAGE_CAPABILITIES,
    [`GET /api/v1/printers/${secondPrinter.id}/capabilities`]: PAGE_CAPABILITIES,
    [`GET ${BASE}`]: [stored, none],
    [`GET /api/v1/printers/${secondPrinter.id}/calibration`]: [{ ...none, tray: "main" }],
    "GET /api/v1/sheet-types": [SHEET_TYPE, oneColumn],
    ...extra,
  };
}

async function open(extra: Record<string, unknown> = {}, session = SIGNED_IN, path = `/calibration?printer=${P}&tray=main`) {
  const api = mockApi(routes(extra));
  const app = await renderApp({ path, session });
  await screen.findByRole("heading", { level: 1, name: "Calibration" });
  return { ...api, ...app };
}

const only = (calls: Call[], method: string, suffix = "") => calls.filter((c) => c.method === method && c.path.endsWith(suffix));
const body = (call: Call | undefined) => JSON.parse(call?.body ?? "null");
const throws = () => {
  throw new TypeError("Failed to fetch");
};
const button = (name: string | RegExp) => screen.findByRole("button", { name });

/**
 * Puts a number into a field, replacing what is there, as one change event.
 * Typing key by key (or even clear + paste through user-event) re-rendered the
 * page and walked the DOM per step: ~300 ms per field, ~100 s for this file,
 * enough to blow the 1 s findBy timeout when 76 files share four cores. These
 * tests are about what the page does with a value, not about keystrokes.
 * The field is found by its label, which is as strict as the accessible name
 * here and much cheaper than a role query.
 */
async function enter(label: string, value: string) {
  await enterAll([[label, value]]);
}

/**
 * Several fields at once, committed in one render. Every change re-renders the whole
 * page (~100 ms in jsdom), so six separate changes cost six renders; inside one act the
 * updates are batched. The page keeps its rows with functional updates, so none is lost.
 */
async function enterAll(pairs: readonly (readonly [string, string])[]) {
  const fields: HTMLElement[] = [];
  for (const [label] of pairs) fields.push(await screen.findByLabelText(label));
  act(() => {
    pairs.forEach(([, value], i) => fireEvent.change(fields[i]!, { target: { value } }));
  });
}

async function fillThree() {
  const list = [
    ["0,2", "-0,1"],
    ["0,4", "0"],
    ["0,6", "0,3"],
  ] as const;
  const crossings = ["S1 · Z1", "S3 · Z1", "S1 · Z11"];
  await enterAll(crossings.flatMap((c, i) => [[`Across at ${c} (mm)`, list[i]![0]], [`Down at ${c} (mm)`, list[i]![1]]] as const));
}

const FIT = {
  values: { offset_x_mm: 0.35, offset_y_mm: -0.15, scale_x: 1.0012, scale_y: 0.9995, rotation_deg: 0.03 },
  residuals_mm: [0.05, 0.42, 0.1, 0.02],
  flagged: [1],
  out_of_range: [],
};

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

describe("the live print status line (#239)", () => {
  const event = (to: string, extra: Record<string, unknown> = {}) =>
    act(() => recordJobEvent({ job_id: JOB, from_state: "queued", to_state: to, queue_depth: 1, error_code: null, ...extra }));
  const lineOf = (name: string) => screen.getByRole("status", { name });
  const printed = async (routesExtra: Record<string, unknown> = {}) => {
    const api = await open({ [`POST ${BASE}/main/page`]: respond(202, { job_id: JOB }), ...routesExtra });
    await userEvent.click(await button("Print calibration page"));
    await within(lineOf("Calibration page status")).findByText("Queued");
    return api;
  };
  // The status element holds only the sentence; the link and Retry sit beside it, in the same line block.
  const around = (line: HTMLElement) => within(line.parentElement!);
  // A real calibration page job, as the hub stores it.
  const PAGE_JOB = { template_key: null, payload: { kind: "calibration_page", tray: "main", detail: { type_key: "L4736REV", version: 1 } } };
  const stack = () => within(screen.getByRole("region", { name: "Print status" }));
  beforeEach(() => resetPrintWatch());

  it("result does not sit in the button row", async () => {
    await printed();
    const line = lineOf("Calibration page status");
    const row = screen.getByRole("link", { name: "Download PDF" }).parentElement!;
    expect(row.contains(line)).toBe(false);
    expect(row.contains(screen.getByRole("link", { name: "Show the job" }))).toBe(false);
    // Below the row, in document order, and in the same step section.
    expect(row.compareDocumentPosition(line) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(row.closest("section")!.contains(line)).toBe(true);
  });

  it("the line is there before the first print, empty, so nothing is added to the page later", async () => {
    await open();
    const line = await screen.findByRole("status", { name: "Calibration page status" });
    expect(line).toHaveAttribute("aria-live", "polite");
    expect(line.textContent).toBe("");
  });

  it("status follows job events queued -> printing -> done", async () => {
    await printed();
    const line = lineOf("Calibration page status");
    expect(around(line).getByRole("link", { name: "Show the job" })).toHaveAttribute("href", `/jobs/${JOB}`);
    event("printing");
    expect(within(line).getByText("Printing")).toBeVisible();
    event("printing", { at_printer: "stopped" });
    expect(within(line).getByText("Stopped at the printer")).toBeVisible();
    event("completed");
    expect(within(line).getByText("Done")).toBeVisible();
    expect(within(line).getByText(/measure the crossings/)).toBeVisible();
    // The stack agrees with the line: both read the same job state.
    expect(within(screen.getByRole("region", { name: "Print status" })).getByText("Done")).toBeVisible();
  });

  it("failed shows the localised error and a Retry that the line follows", async () => {
    const { calls } = await printed({
      [`GET /api/v1/jobs/${JOB}`]: job(JOB, P, "failed", { ...PAGE_JOB, error: "printer_offline: down" }),
      [`POST /api/v1/jobs/${JOB}/retry`]: job(RETRY, P, "queued", PAGE_JOB),
    });
    event("failed", { error_code: "printer_offline" });
    const line = lineOf("Calibration page status");
    expect(within(line).getByText("Failed")).toBeVisible();
    expect(within(line).getByText(/The printer could not be reached/)).toBeVisible();
    fireEvent.click(await around(line).findByRole("button", { name: "Retry" }));
    await waitFor(() => expect(within(line).getByText("Queued")).toBeVisible());
    expect(calls.some((c) => c.method === "POST" && c.path === `/api/v1/jobs/${JOB}/retry`)).toBe(true);
    expect(around(line).getByRole("link", { name: "Show the job" })).toHaveAttribute("href", `/jobs/${RETRY}`);
    act(() => recordJobEvent({ job_id: RETRY, from_state: "queued", to_state: "completed", queue_depth: 0, error_code: null }));
    expect(within(line).getByText("Done")).toBeVisible();
  });

  it("Retry follows the hub's job record, not the event: a record that does not say failed yet offers none", async () => {
    // A real calibration page job is retryable once it failed; here the record still says "done" while the event
    // already said "failed" (the two disagree for a moment), and the hub's record decides.
    const { calls } = await printed({ [`GET /api/v1/jobs/${JOB}`]: job(JOB, P, "done", PAGE_JOB) });
    event("failed", { error_code: "interrupted" });
    const line = lineOf("Calibration page status");
    expect(await within(line).findByText(/interrupted while it was printing/)).toBeVisible();
    await waitFor(() => expect(calls.some((c) => c.path === `/api/v1/jobs/${JOB}`)).toBe(true));
    expect(around(line).queryByRole("button", { name: "Retry" })).toBeNull();
  });

  it("a refused retry says why, in words", async () => {
    await printed({
      [`GET /api/v1/jobs/${JOB}`]: job(JOB, P, "failed", { ...PAGE_JOB, error: "ipp_aborted: x" }),
      [`POST /api/v1/jobs/${JOB}/retry`]: respond(409, apiErrorBody("printer_disabled", "off")),
    });
    event("failed", { error_code: "ipp_aborted" });
    const line = lineOf("Calibration page status");
    fireEvent.click(await around(line).findByRole("button", { name: "Retry" }));
    expect(await around(line).findByText("The printer is switched off. Switch it on in the settings, then retry.")).toBeVisible();
  });

  it("announces once: the line is live, the stack shows the card without a live region of its own", async () => {
    await printed({ [`GET /api/v1/jobs/${JOB}`]: job(JOB, P, "failed", { ...PAGE_JOB, error: "ipp_aborted: x" }) });
    // The card is there from the first moment, and in no live region (the line announces it).
    expect(stack().getByText("Queued").closest("[aria-live]")).toBeNull();
    event("failed", { error_code: "ipp_aborted" });
    const line = lineOf("Calibration page status");
    expect(stack().getByText("Failed").closest("[aria-live]")).toBeNull();
    expect(line).toHaveAttribute("aria-live", "polite");
    // The live element holds only the sentence: the controls are beside it, so a state change does not re-read them.
    expect(within(line).queryByRole("link")).toBeNull();
    expect(within(line).queryByRole("button")).toBeNull();
    expect(await around(line).findByRole("button", { name: "Retry" })).toBeVisible();
  });

  it("the stack announces the card again once the page line is gone", async () => {
    await printed({ [`GET /api/v1/jobs/${JOB}`]: job(JOB, P, "failed", { ...PAGE_JOB, error: "ipp_aborted: x" }) });
    event("failed", { error_code: "ipp_aborted" });
    expect(stack().getByText("Failed").closest("[aria-live]")).toBeNull();
    await userEvent.click(screen.getAllByRole("link", { name: "Jobs" })[0]!);
    await waitFor(() => expect(stack().getByText("Failed").closest("[aria-live]")?.getAttribute("aria-live")).toBe("assertive"));
  });

  it("Retry pressed in the line and in the stack before the first answer clones the job once", async () => {
    let answer: (() => void) | undefined;
    const { calls } = await printed({
      [`GET /api/v1/jobs/${JOB}`]: job(JOB, P, "failed", { ...PAGE_JOB, error: "ipp_aborted: x" }),
      [`POST /api/v1/jobs/${JOB}/retry`]: () => new Promise((resolve) => (answer = () => resolve(job(RETRY, P, "queued", PAGE_JOB)))),
    });
    event("failed", { error_code: "ipp_aborted" });
    const line = lineOf("Calibration page status");
    fireEvent.click(await around(line).findByRole("button", { name: "Retry" }));
    fireEvent.click(await stack().findByRole("button", { name: "Retry" }));
    await waitFor(() => expect(calls.filter((c) => c.method === "POST" && c.path.endsWith("/retry"))).toHaveLength(1));
    act(() => answer?.());
    await waitFor(() => expect(within(line).getByText("Queued")).toBeVisible());
    expect(around(line).getByRole("link", { name: "Show the job" })).toHaveAttribute("href", `/jobs/${RETRY}`);
    expect(calls.filter((c) => c.method === "POST" && c.path.endsWith("/retry"))).toHaveLength(1);
    // One card, following the new job.
    expect(stack().getAllByText("Queued")).toHaveLength(1);
  });

  it("a Retry pressed in the stack moves the line to the new job", async () => {
    const { calls } = await printed({
      [`GET /api/v1/jobs/${JOB}`]: job(JOB, P, "failed", { ...PAGE_JOB, error: "ipp_aborted: x" }),
      [`POST /api/v1/jobs/${JOB}/retry`]: job(RETRY, P, "queued", PAGE_JOB),
    });
    event("failed", { error_code: "ipp_aborted" });
    const line = lineOf("Calibration page status");
    fireEvent.click(await stack().findByRole("button", { name: "Retry" }));
    await waitFor(() => expect(within(line).getByText("Queued")).toBeVisible());
    expect(around(line).getByRole("link", { name: "Show the job" })).toHaveAttribute("href", `/jobs/${RETRY}`);
    expect(calls.filter((c) => c.method === "POST" && c.path.endsWith("/retry"))).toHaveLength(1);
    act(() => recordJobEvent({ job_id: RETRY, from_state: "queued", to_state: "completed", queue_depth: 0, error_code: null }));
    expect(within(line).getByText("Done")).toBeVisible();
  });

  it("the check page has its own line under its own button", async () => {
    await open({ [`POST ${BASE}/main/page`]: respond(202, { job_id: JOB }) });
    await userEvent.click(await button("Check print with correction"));
    const line = await screen.findByRole("status", { name: "Check page status" });
    await within(line).findByText("Queued");
    event("completed");
    expect(within(line).getByText(/within 0\.5 mm/)).toBeVisible();
    expect(lineOf("Calibration page status").textContent).toBe("");
    const row = screen.getByRole("button", { name: "Check print with correction" }).parentElement!;
    expect(row.contains(line)).toBe(false);
  });

  it("a refusal because the printer is held after a device swap stays in the page", async () => {
    await open({
      [`POST ${BASE}/main/page`]: () =>
        respond(409, { detail: { type: "printer-identity-mismatch", title: "Held", status: 409, detail: "held" } }),
    });
    await userEvent.click(await button("Print calibration page"));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("This printer may be a different device now.");
    const row = screen.getByRole("link", { name: "Download PDF" }).parentElement!;
    expect(row.contains(alert)).toBe(false);
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

