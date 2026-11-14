// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { components } from "../../api/schema.gen";
import { renderApp, SIGNED_IN } from "../../test-utils";
import {
  apiErrorBody,
  mockApi,
  PAGE_CAPABILITIES,
  PAGE_PRINTER,
  PRINTER_A,
  respond,
  sheetRead,
  SHEET_TYPE,
  type Call,
} from "../test-api";

type Schemas = components["schemas"];
const PRINT_SESSION = { ...SIGNED_IN, scope: "print" as const };

const CREATED: Schemas["SheetCreated"] = { ...sheetRead("L4736-0004", { used: [1, 2] }), job_id: null };
const MARGIN_OK: Schemas["MarginCheckRead"] = {
  band: "top",
  bands_mm: { top: 8, bottom: 8, left: 0, right: 0 } as Schemas["MarginBandsMm"],
  corner: null,
  feed_mark: false,
  printable: true,
  qr: true,
  reason: null,
  usable_mm: 8,
};
const TWO_TYPES = [SHEET_TYPE, { ...SHEET_TYPE, key: "my-small", description: "Tiny", allow_qr: false }];

// Whole-app renders with a dialog and a select: under coverage and a loaded runner they need more than 5 s.
vi.setConfig({ testTimeout: 10_000 });

afterEach(() => vi.unstubAllGlobals());

function setup(routes: Record<string, unknown> = {}) {
  return mockApi({
    "GET /api/v1/sheets": [],
    "GET /api/v1/sheet-types": TWO_TYPES,
    "GET /api/v1/printers": [PRINTER_A, PAGE_PRINTER],
    [`GET /api/v1/printers/${PAGE_PRINTER.id}/capabilities`]: PAGE_CAPABILITIES,
    "GET /api/v1/sheets/next-code": { code: "L4736-0004", hint: "probable" },
    "GET /api/v1/sheets/margin-check": MARGIN_OK,
    "POST /api/v1/sheets": CREATED,
    ...routes,
  });
}

async function openDialog() {
  const view = await renderApp({ path: "/sheets", session: PRINT_SESSION });
  await userEvent.click(await screen.findByRole("button", { name: "New sheet" }));
  return { ...view, dialog: await screen.findByRole("dialog", { name: "Add a sheet" }) };
}

async function pick(label: string | RegExp, option: string | RegExp) {
  await userEvent.click(screen.getByRole("button", { name: label }));
  await userEvent.click(await screen.findByRole("option", { name: option }));
}

const chooseType = () => pick(/Sheet type/, /\(L4736REV\)/);
const choosePrinter = () => pick(/Printer/, "Office laser");
const posts = (calls: Call[]) => calls.filter((c) => c.method === "POST" && c.path === "/api/v1/sheets");
const body = (call: Call) => JSON.parse(call.body!) as Record<string, unknown>;
const cell = (n: number) => screen.getByRole("gridcell", { name: new RegExp(`^Cell ${n},`) });

describe("the add-a-sheet dialog", () => {
  it("sends the cells marked on the grid, the margin placement and the type", async () => {
    const { calls } = setup();
    await openDialog();
    await chooseType();
    await userEvent.click(cell(2));
    await userEvent.click(cell(1));
    expect(screen.getByText("2 cells marked as used")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Add sheet" }));
    await waitFor(() => expect(posts(calls)).toHaveLength(1));
    expect(body(posts(calls)[0]!)).toEqual({ type: "L4736REV", used_cells: [{ cell: 1 }, { cell: 2 }], id_placement: "margin" });
  });

  it("marks a cell used and then unmarks it again with a second tap", async () => {
    const { calls } = setup();
    await openDialog();
    await chooseType();
    await userEvent.click(cell(5));
    expect(cell(5)).toHaveAccessibleName(/used/);
    await userEvent.click(cell(5));
    expect(cell(5)).toHaveAccessibleName(/free/);
    await userEvent.click(screen.getByRole("button", { name: "Add sheet" }));
    await waitFor(() => expect(posts(calls)).toHaveLength(1));
    expect(body(posts(calls)[0]!).used_cells).toEqual([]);
  });

  it("needs a type before it can add anything", async () => {
    setup();
    await openDialog();
    expect(screen.getByRole("button", { name: "Add sheet" })).toBeDisabled();
    expect(screen.queryByRole("grid")).toBeNull();
    await chooseType();
    expect(screen.getByRole("button", { name: "Add sheet" })).toBeEnabled();
  });

  it("starts the marks again when the type changes (the other type has other cells)", async () => {
    setup();
    await openDialog();
    await chooseType();
    await userEvent.click(cell(3));
    await pick(/Sheet type/, /my-small/);
    expect(screen.queryByText(/cells? marked as used/)).toBeNull();
    expect(cell(3)).toHaveAccessibleName(/free/);
  });

  it("preselects the margin, and it stays enabled and is sent as margin even when this printer cannot print the ID", async () => {
    const { calls } = setup({
      "GET /api/v1/sheets/margin-check": { ...MARGIN_OK, band: null, printable: false, qr: false, reason: "no band wide enough" },
    });
    await openDialog();
    await chooseType();
    const margin = screen.getByRole("radio", { name: /In the margin/ });
    expect(margin).toBeChecked();
    await choosePrinter();
    expect(await screen.findByText("The ID will not be printed on this printer, add it by hand.")).toBeVisible();
    expect(margin).toBeEnabled();
    expect(margin).toBeChecked();
    await userEvent.click(screen.getByRole("button", { name: "Add sheet" }));
    await waitFor(() => expect(posts(calls)).toHaveLength(1));
    expect(body(posts(calls)[0]!).id_placement).toBe("margin");
  });

  it("names the band, with QR or text only, once a printer is chosen", async () => {
    const first = setup();
    const view = await openDialog();
    await chooseType();
    expect(screen.queryByText(/margin, with QR/)).toBeNull(); // no printer, nothing to check
    await choosePrinter();
    expect(await screen.findByText("The ID will be printed in the top margin, with QR.")).toBeVisible();
    expect(first.calls.some((c) => c.path === "/api/v1/sheets/margin-check")).toBe(true);
    view.unmount();

    setup({ "GET /api/v1/sheets/margin-check": { ...MARGIN_OK, band: "left", qr: false } });
    await openDialog();
    await chooseType();
    await choosePrinter();
    expect(await screen.findByText("The ID will be printed in the left margin, text only.")).toBeVisible();
  });

  it("asks the margin check with the chosen tray, and with the default tray before any is chosen", async () => {
    const { calls } = setup();
    await openDialog();
    await chooseType();
    await choosePrinter();
    await screen.findByText("The ID will be printed in the top margin, with QR.");
    const checks = () => calls.filter((c) => c.path === "/api/v1/sheets/margin-check").map((c) => new URLSearchParams(c.search));
    expect(checks().at(-1)!.get("tray")).toBe("main"); // the default tray
    expect(checks().at(-1)!.get("printer")).toBe(PAGE_PRINTER.id);
    expect(checks().at(-1)!.get("type")).toBe("L4736REV");

    await pick(/Tray/, /Bypass/);
    await waitFor(() => expect(checks().at(-1)!.get("tray")).toBe("bypass"));
  });

  it("offers only enabled page printers, never a tape printer", async () => {
    setup({
      "GET /api/v1/printers": [PRINTER_A, PAGE_PRINTER, { ...PAGE_PRINTER, id: "55555555-5555-4555-8555-555555555555", name: "Off laser", enabled: false }],
    });
    await openDialog();
    await chooseType();
    await userEvent.click(screen.getByRole("button", { name: /Printer/ }));
    const options = (await screen.findAllByRole("option")).map((o) => o.textContent);
    expect(options).toEqual(["No printer", "Office laser"]);
  });

  it("the first free cell needs a printer and a tray, and the button then prints the ID label", async () => {
    const { calls } = setup({
      "POST /api/v1/sheets": { ...CREATED, id_placement: "cell", job_id: "66666666-6666-4666-8666-666666666666" },
    });
    await openDialog();
    await chooseType();
    await userEvent.click(screen.getByRole("radio", { name: /In the first free cell/ }));
    const add = screen.getByRole("button", { name: "Add and print ID label" });
    expect(add).toBeDisabled();
    expect(screen.getByText("Choose a printer and a tray to print the ID label.")).toBeVisible();

    await choosePrinter();
    await waitFor(() => expect(screen.getByRole("button", { name: "Add and print ID label" })).toBeEnabled());
    await pick(/Tray/, /Bypass/);
    await userEvent.click(screen.getByRole("button", { name: "Add and print ID label" }));
    await waitFor(() => expect(posts(calls)).toHaveLength(1));
    expect(body(posts(calls)[0]!)).toEqual({
      type: "L4736REV",
      used_cells: [],
      id_placement: "cell",
      printer: PAGE_PRINTER.id,
      tray: "bypass",
    });
    const job = await screen.findByRole("link", { name: "Show the ID label job" });
    expect(job).toHaveAttribute("href", "/jobs/66666666-6666-4666-8666-666666666666");
  });

  it("a printer that reports no trays cannot print the ID label from here", async () => {
    setup({ [`GET /api/v1/printers/${PAGE_PRINTER.id}/capabilities`]: { ...PAGE_CAPABILITIES, trays: [] } });
    await openDialog();
    await chooseType();
    await userEvent.click(screen.getByRole("radio", { name: /In the first free cell/ }));
    await choosePrinter();
    expect(await screen.findByText("This printer reports no trays, so it cannot print the ID label.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Add and print ID label" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: /Tray/ })).toBeNull();
  });

  it("shows the probable code, and the real code from the answer when it differs", async () => {
    setup({ "POST /api/v1/sheets": { ...CREATED, code: "L4736-0005" } });
    await openDialog();
    await chooseType();
    expect(await screen.findByText((_, el) => el?.tagName === "P" && el.textContent === "It will probably become L4736-0004.")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Add sheet" }));
    expect(await screen.findByText("Sheet L4736-0005 was added.")).toBeVisible();
    expect(screen.getByText("The number is L4736-0005, not L4736-0004: another sheet was added in the meantime.")).toBeVisible();
    expect(screen.getByRole("link", { name: "Open L4736-0005" })).toHaveAttribute("href", "/sheets/L4736-0005");
  });

  it("does not make a fuss when the code is the one it said", async () => {
    setup();
    await openDialog();
    await chooseType();
    await userEvent.click(screen.getByRole("button", { name: "Add sheet" }));
    expect(await screen.findByText("Sheet L4736-0004 was added.")).toBeVisible();
    expect(screen.queryByText(/another sheet was added/)).toBeNull();
  });

  it("tells that the labels of a type are too small for a QR code", async () => {
    setup();
    await openDialog();
    await chooseType();
    expect(screen.queryByText(/too small for a QR code/)).toBeNull();
    await pick(/Sheet type/, /my-small/);
    expect(screen.getByText("The labels of this type are too small for a QR code, so the ID is printed as text only.")).toBeVisible();
  });

  it("keeps the measurements of the type one tap away", async () => {
    setup();
    await openDialog();
    await chooseType();
    await userEvent.click(screen.getByText("Measurements of this type"));
    expect(await screen.findByText("Label size")).toBeVisible();
  });

  it("shows why it failed, in words, and keeps what was entered", async () => {
    setup({ "POST /api/v1/sheets": () => respond(409, apiErrorBody("sheet_type_archived", "archived")) });
    await openDialog();
    await chooseType();
    await userEvent.click(cell(1));
    await userEvent.click(screen.getByRole("button", { name: "Add sheet" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("This type is archived. Bring it back first.");
    expect(screen.getByText("1 cell marked as used")).toBeVisible();
  });

  it("when only the ID label failed the sheet exists, and the dialog says so with a link", async () => {
    setup({
      "POST /api/v1/sheets": () =>
        respond(500, apiErrorBody("sheet_id_job_failed", "The sheet was created, but its ID label could not be queued.", { sheet_code: "L4736-0004" })),
    });
    await openDialog();
    await chooseType();
    await userEvent.click(screen.getByRole("radio", { name: /In the first free cell/ }));
    await choosePrinter();
    await waitFor(() => expect(screen.getByRole("button", { name: "Add and print ID label" })).toBeEnabled());
    await userEvent.click(screen.getByRole("button", { name: "Add and print ID label" }));
    expect(await screen.findByText("Sheet L4736-0004 was added, but its ID label could not be queued.")).toBeVisible();
    expect(screen.getByRole("link", { name: "Open L4736-0004" })).toHaveAttribute("href", "/sheets/L4736-0004");
  });

  it("a partly queued ID label is said in words, the marks stay and the form stays open", async () => {
    setup({
      "POST /api/v1/sheets": () =>
        respond(502, apiErrorBody("print_interrupted", "The print stopped.", { batch_id: "b1", job_ids: ["66666666-6666-4666-8666-666666666666"] })),
    });
    await openDialog();
    await chooseType();
    await userEvent.click(cell(2));
    await userEvent.click(screen.getByRole("radio", { name: /In the first free cell/ }));
    await choosePrinter();
    await waitFor(() => expect(screen.getByRole("button", { name: "Add and print ID label" })).toBeEnabled());
    await userEvent.click(screen.getByRole("button", { name: "Add and print ID label" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The ID label was queued only in part. Look at the print jobs.");
    expect(screen.getByRole("button", { name: "Add and print ID label" })).toBeVisible();
    expect(screen.getByText("1 cell marked as used")).toBeVisible();
    expect(screen.queryByText(/was added/)).toBeNull();
  });

  it("a network failure while adding with an ID label says the server cannot be reached and keeps the form", async () => {
    setup({
      "POST /api/v1/sheets": () => {
        throw new TypeError("Failed to fetch");
      },
    });
    await openDialog();
    await chooseType();
    await userEvent.click(cell(3));
    await userEvent.click(screen.getByRole("radio", { name: /In the first free cell/ }));
    await choosePrinter();
    await waitFor(() => expect(screen.getByRole("button", { name: "Add and print ID label" })).toBeEnabled());
    await userEvent.click(screen.getByRole("button", { name: "Add and print ID label" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The server cannot be reached.");
    expect(screen.getByText("1 cell marked as used")).toBeVisible();
    // The failure is not final: the button is usable again.
    expect(screen.getByRole("button", { name: "Add and print ID label" })).toBeEnabled();
  });

  it("a failed capabilities request is not reported as a printer without trays", async () => {
    const { calls } = setup({ [`GET /api/v1/printers/${PAGE_PRINTER.id}/capabilities`]: () => respond(403, { detail: "no" }) });
    await openDialog();
    await chooseType();
    await userEvent.click(screen.getByRole("radio", { name: /In the first free cell/ }));
    await choosePrinter();
    expect(await screen.findByText("The printer could not be asked for its trays. Try again in a moment.")).toBeVisible();
    expect(screen.queryByText(/reports no trays/)).toBeNull();
    expect(screen.getByRole("button", { name: "Add and print ID label" })).toBeDisabled();
    // Without the trays the margin check would run for a tray nobody chose: it waits.
    expect(calls.some((c) => c.path === "/api/v1/sheets/margin-check")).toBe(false);
  });

  it("names types by their label with the key, in the dialog's list and on the trigger with the full text as a tooltip", async () => {
    setup();
    await openDialog();
    await userEvent.click(screen.getByRole("button", { name: /Sheet type/ }));
    expect((await screen.findAllByRole("option")).map((o) => o.textContent)).toEqual([
      "Choose a sheet type",
      "Example Labels L4736REV-25 (L4736REV) · 45.7 × 21.2 mm",
      "Example Labels L4736REV-25 (my-small) · 45.7 × 21.2 mm",
    ]);
    await userEvent.click(screen.getByRole("option", { name: /\(my-small\)/ }));
    expect(screen.getByTitle("Example Labels L4736REV-25 (my-small) · 45.7 × 21.2 mm")).toBeInTheDocument();
  });

  it("starts empty when it is opened again", async () => {
    setup();
    const { dialog } = await openDialog();
    await chooseType();
    await userEvent.click(cell(4));
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await userEvent.click(screen.getByRole("button", { name: "New sheet" }));
    await screen.findByRole("dialog", { name: "Add a sheet" });
    expect(screen.queryByRole("grid")).toBeNull();
  });
});
