import { act, configure, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { renderApp } from "../../../test-utils";
import { CART_KEY, reloadCart } from "../../lookup/cart";
import { mockApi, PAGE_PRINTER, PRINTER_A, respond, SHEET_TYPE, pageStatus, sheetRead, type Call } from "../../test-api";
import { BATCH, JOB, NEW_9, P, USED_17, body, conflict, expectType, pick, pickType, previewFor, typeBox, previewPage, reason, routes, sheet } from "./testkit";

const PREVIEW = `/api/v1/print/${P}/sheet/preview`;
const PRINT = `/api/v1/print/${P}/sheet`;

// The preview is requested 400 ms after the last change (PREVIEW_DEBOUNCE_MS), so every
// findBy that waits for it starts with a 400 ms real-time wait inside the default 1 s window.
// With 76 files sharing four cores in the full run that margin is thin. The window is widened
// for this file only and restored afterwards; the assertions are unchanged.
let defaultAsyncTimeout = 1000;
beforeAll(() => {
  configure((current) => {
    defaultAsyncTimeout = current.asyncUtilTimeout;
    return { asyncUtilTimeout: 5000 };
  });
});
afterAll(() => configure({ asyncUtilTimeout: defaultAsyncTimeout }));

// Every test here boots the whole app (about 1 s alone before the first assertion) and each
// click re-renders it (100-500 ms in jsdom); on its own the slowest tests take 2-2.6 s. The
// coverage run on four shared cores is about 2.5 times slower, which put the busiest test at
// 5.3 s, past the default 5 s per test. The per-test limit is widened for this file only, with
// the same reasoning as the async window above; vi.setConfig is scoped to this file.
vi.setConfig({ testTimeout: 15_000 });

beforeEach(() => {
  localStorage.clear();
  reloadCart();
});
afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
  reloadCart();
});

const previews = (calls: Call[]) => calls.filter((c) => c.path === PREVIEW);
const printCalls = (calls: Call[]) => calls.filter((c) => c.path === PRINT && c.method === "POST");

/** The item view of Flour (Grocy 7) with a page printer first in the list. */
async function itemView(r: Record<string, unknown> = routes(), copies = 9) {
  const api = mockApi(r);
  const view = await renderApp({ path: "/lookup/grocy/7" });
  await screen.findByRole("heading", { level: 2, name: "Print onto a sheet" });
  if (copies !== 1) {
    fireEvent.change(screen.getByRole("spinbutton", { name: "Copies" }), { target: { value: String(copies) } });
  }
  return { ...api, ...view };
}

async function cartView(path: string, items: Array<Record<string, unknown>>, r: Record<string, unknown> = routes()) {
  localStorage.setItem(CART_KEY, JSON.stringify(items));
  reloadCart();
  const api = mockApi(r);
  const view = await renderApp({ path });
  return { ...api, ...view };
}
/** Presses the print button once the preview has arrived and enabled it. */
async function pressPrint(name: string | RegExp = "Print onto sheet") {
  const button = await screen.findByRole("button", { name });
  await waitFor(() => expect(button).toBeEnabled());
  await userEvent.click(button);
}
const LINE = (id: string, copies: number, name = `Item ${id}`, app = "grocy") => ({ app, id, name, content_type: "qr_two_lines", copies });

describe("the sheet section replaces the tape preview for page printers", () => {
  it("a tape printer keeps the tape preview and shows no sheet section", async () => {
    const { calls } = mockApi(routes({ printers: [PRINTER_A] }));
    await renderApp({ path: "/lookup/grocy/7" });
    expect(await screen.findByRole("img", { name: "Label preview" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Print now" })).toBeEnabled();
    expect(screen.queryByRole("heading", { name: "Print onto a sheet" })).toBeNull();
    expect(calls.some((c) => c.path === PREVIEW)).toBe(false);
  });

  it("a page printer shows the sheet section, no tape preview and no one-label print", async () => {
    const { calls } = await itemView(routes(), 1);
    expect(screen.queryByRole("img", { name: "Label preview" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Print now" })).toBeNull();
    expect(calls.some((c) => c.path === "/api/v1/render/preview")).toBe(false);
    expect(screen.getByRole("button", { name: "Add to cart" })).toBeVisible();
  });

  it("the printer list names kind and state", async () => {
    await itemView(routes({ status: pageStatus(P, { printer_state: "stopped", state_reasons: [reason("toner-empty", "error", true)] }) }), 1);
    const picker = screen.getByRole("combobox", { name: "Printer" });
    await waitFor(() => expect(within(picker).getAllByRole("option")[0]).toHaveTextContent("Office laser · Page printer · Stopped"));
  });

  it("only enabled page printers are offered", async () => {
    mockApi(routes({ printers: [{ ...PAGE_PRINTER, enabled: false }, PRINTER_A] }));
    await renderApp({ path: "/lookup/grocy/7" });
    expect(await screen.findByRole("img", { name: "Label preview" })).toBeVisible();
    expect(screen.queryByRole("heading", { name: "Print onto a sheet" })).toBeNull();
  });
});

describe("the printer row", () => {
  it("says the state in words, the toner per marker and the jobs from other computers", async () => {
    await itemView(routes({ status: pageStatus(P, { jobs_ahead: 2 }) }), 1);
    const section = screen.getByRole("region", { name: "Print onto a sheet" });
    expect(await within(section).findByText("Ready")).toBeVisible();
    expect(within(section).getByText("Black toner")).toBeVisible();
    expect(within(section).getByText("80 %")).toBeVisible();
    expect(within(section).getByText("2 jobs from other computers ahead")).toBeVisible();
  });

  it("says nothing about other jobs when none are ahead", async () => {
    await itemView(routes(), 1);
    await screen.findByText("Ready");
    expect(screen.queryByText(/from other computers? ahead|from another computer ahead/)).toBeNull();
  });

  it("a stopped printer gets an alert with the reason, and the button says Add to print queue", async () => {
    await itemView(routes({ status: pageStatus(P, { printer_state: "stopped", state_reasons: [reason("toner-empty", "error", true)] }) }), 1);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("toner empty");
    expect(alert).toHaveTextContent("print queue");
    const queue = await screen.findByRole("button", { name: "Add to print queue" });
    await waitFor(() => expect(queue).toBeEnabled());
    expect(screen.queryByRole("button", { name: "Print onto sheet" })).toBeNull();
  });

  it("a ready printer prints onto the sheet", async () => {
    await itemView(routes(), 1);
    const button = await screen.findByRole("button", { name: "Print onto sheet" });
    await waitFor(() => expect(button).toBeEnabled());
  });
});

describe("tray, sheet type and the sheet", () => {
  it("offers the enabled trays with the default preselected, sends it, and shows the load hint under the preview", async () => {
    const hint = "Put L4736-0001 into the manual tray, written side down, top edge first";
    const { calls } = await itemView(routes({ preview: previewFor("L4736-0001", NEW_9, USED_17, {}, { load_hint: hint }) }));
    expect(await screen.findByRole("button", { name: /Main tray/ })).toBeVisible();
    expect(await screen.findByText(hint)).toBeVisible();
    await waitFor(() => expect(previews(calls).length).toBeGreaterThan(0));
    expect(body(previews(calls).at(-1)!).tray).toBe("main");
    await pick(/Tray/, /Bypass/);
    await waitFor(() => expect(body(previews(calls).at(-1)!).tray).toBe("bypass"));
  });

  it("a printer without trays has no tray choice and sends no tray", async () => {
    const { calls } = await itemView(routes({ status: pageStatus(P, { trays: [] }) }), 1);
    await waitFor(() => expect(previews(calls).length).toBeGreaterThan(0));
    expect(screen.queryByRole("button", { name: /^Tray/ })).toBeNull();
    expect(body(previews(calls)[0]!).tray ?? null).toBeNull();
  });

  it("remembers the sheet type per printer", async () => {
    const other = { ...SHEET_TYPE, key: "other-type", product_codes: ["OT-1"], vendor: "Other" };
    await itemView(routes({ types: [SHEET_TYPE, other] }), 1);
    await pickType(/other-type/);
    expect(localStorage.getItem(`lph.sheetType.${P}`)).toBe("other-type");
  });

  it("starts with the type used last on this printer", async () => {
    const other = { ...SHEET_TYPE, key: "other-type", product_codes: ["OT-1"], vendor: "Other" };
    localStorage.setItem(`lph.sheetType.${P}`, "other-type");
    await itemView(routes({ types: [SHEET_TYPE, other] }), 1);
    await expectType(/other-type/);
  });

  it("lists the sheets that hold everything first, with the free count and 'too small' for the others", async () => {
    await itemView(routes({ sheets: [sheet("L4736-0010", 43), sheet("L4736-0011", 18)] }));
    await userEvent.click(await screen.findByRole("combobox", { name: "Sheet" }));
    const options = (await screen.findAllByRole("option")).map((o) => o.textContent);
    expect(options[0]).toMatch(/L4736-0011.*30 free.*fits 9/);
    expect(options[1]).toMatch(/L4736-0010.*5 free.*too small/);
    expect(options.at(-1)).toMatch(/New .* sheet.*L4736-0005/);
  });

  it("searches by code", async () => {
    await itemView(routes({ sheets: [sheet("L4736-0010", 43), sheet("L4736-0011", 18)] }));
    const box = await screen.findByRole("combobox", { name: "Sheet" });
    await userEvent.click(box);
    await userEvent.clear(box);
    await userEvent.type(box, "0010");
    const options = await screen.findAllByRole("option");
    expect(options.map((o) => o.textContent).join("|")).toMatch(/L4736-0010/);
    expect(options.map((o) => o.textContent).join("|")).not.toMatch(/L4736-0011/);
  });

  it("previews onto the best fitting sheet at first, then onto the one chosen", async () => {
    const { calls } = await itemView(routes({ sheets: [sheet("L4736-0010", 43), sheet("L4736-0011", 18)] }));
    await waitFor(() => expect(previews(calls).length).toBeGreaterThan(0));
    expect(body(previews(calls)[0]!).placements).toEqual([{ sheet: "L4736-0011", cells: "first_free" }]);
    expect(body(previews(calls)[0]!).items).toHaveLength(9);
    await userEvent.click(await screen.findByRole("combobox", { name: "Sheet" }));
    await userEvent.click(await screen.findByRole("option", { name: /L4736-0010/ }));
    await waitFor(() => expect(body(previews(calls).at(-1)!).placements[0]).toMatchObject({ sheet: "L4736-0010" }));
  });

  it("a new sheet is requested without cells of its own and with the ID in the margin", async () => {
    const { calls } = await itemView(routes({ sheets: [] , preview: previewFor(null, NEW_9, [])}));
    await waitFor(() => expect(previews(calls).length).toBeGreaterThan(0));
    expect(body(previews(calls)[0]!).placements).toEqual([{ new_sheet: { type: "L4736REV", id_placement: "margin" }, cells: "first_free" }]);
    expect(await screen.findByText(/become.*L4736-0005|L4736-0005/)).toBeVisible();
  });
});

describe("an archived sheet type", () => {
  const OLD = { ...SHEET_TYPE, key: "OLDTYPE", product_codes: ["OLD-1"], vendor: "Old", archived_at: "2026-11-01T00:00:00Z" };
  const oldSheet = (code: string, used: number) => sheet(code, used, { type_key: "OLDTYPE", type_label: "Old OLD-1" });

  it("stays selectable for its sheets with free cells, prints onto the existing sheet and offers no new one", async () => {
    localStorage.setItem(`lph.sheetType.${P}`, "OLDTYPE");
    const { calls } = await itemView(routes({ types: [SHEET_TYPE, OLD], sheets: [oldSheet("OLDX-0001", 17)], preview: previewFor("OLDX-0001", NEW_9, USED_17) }));
    await expectType(/OLDTYPE.*archived/);
    expect(screen.getByText(/This sheet type is archived/)).toBeVisible();
    await waitFor(() => expect(previews(calls).length).toBeGreaterThan(0));
    expect(body(previews(calls).at(-1)!).placements).toEqual([{ sheet: "OLDX-0001", cells: "first_free" }]);
    await userEvent.click(await screen.findByRole("combobox", { name: "Sheet" }));
    const options = (await screen.findAllByRole("option")).map((o) => o.textContent);
    expect(options).toHaveLength(1);
    expect(options.join("|")).not.toMatch(/New .* sheet/);
  });

  it("prints onto the existing sheet of the archived type", async () => {
    localStorage.setItem(`lph.sheetType.${P}`, "OLDTYPE");
    const { calls } = await itemView(routes({ types: [SHEET_TYPE, OLD], sheets: [oldSheet("OLDX-0001", 17)], preview: previewFor("OLDX-0001", NEW_9, USED_17) }));
    // The server leaves archived types out unless asked: the mock cannot, so the question itself is checked.
    expect(calls.filter((c) => c.path === "/api/v1/sheet-types").every((c) => c.search.includes("include_archived=true"))).toBe(true);
    await pressPrint();
    await waitFor(() => expect(body(printCalls(calls).at(-1)!).placements[0]).toMatchObject({ sheet: "OLDX-0001" }));
  });

  it("a full sheet of the type does not make it a new-sheet target: the rest cannot go onto a new sheet either", async () => {
    localStorage.setItem(`lph.sheetType.${P}`, "OLDTYPE");
    const more = routes({
      types: [SHEET_TYPE, OLD],
      sheets: [oldSheet("OLDX-0001", 43)],
      preview: conflict(409, "insufficient_cells", "Not enough.", { free_cells: [5], needed: 9, shortfall: 4 }),
    });
    await itemView(more);
    expect(await screen.findByText(/has only 5 free cells/)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Put the rest onto a new sheet" })).toBeNull();
  });

  it("a chosen archived type whose last free cell is taken by a sheet.updated event gives way to an offered type and offers no new sheet", async () => {
    const sources: Array<{ emit: (type: string, printerId: string | null, data: unknown) => void }> = [];
    class FakeEventSource {
      private listeners = new Map<string, Array<(e: MessageEvent) => void>>();
      onopen: (() => void) | null = null;
      onerror: (() => void) | null = null;
      constructor() {
        sources.push(this);
      }
      addEventListener(type: string, fn: (e: MessageEvent) => void) {
        this.listeners.set(type, [...(this.listeners.get(type) ?? []), fn]);
      }
      close() {}
      emit(type: string, printerId: string | null, data: unknown) {
        const payload = JSON.stringify({ channel: "hub", printer_id: printerId, type, ts: "2026-01-01T00:00:00Z", data });
        for (const fn of this.listeners.get(type) ?? []) fn(new MessageEvent(type, { data: payload }));
      }
    }
    vi.stubGlobal("EventSource", FakeEventSource);
    let taken = false;
    const { calls } = await itemView(
      routes({
        types: [SHEET_TYPE, OLD],
        extra: {
          "GET /api/v1/sheets": () => [taken ? oldSheet("OLDX-0001", 48) : oldSheet("OLDX-0001", 47), sheet("L4736-0001", 17)],
        },
      }),
      1,
    );
    // The user picks the archived type by hand: that is a typeChoice, not a default.
    await pickType(/OLDTYPE/);
    await expectType(/OLDTYPE.*archived/);
    await waitFor(() => expect(sources.length).toBeGreaterThan(0));
    taken = true;
    await act(async () => {
      sources.at(-1)!.emit("sheet.updated", null, { code: "OLDX-0001", free: 0, total: 48, changed: [48], state: "active" });
    });
    // The type is no longer offered, so the choice moves to an offered type ...
    await expectType(/L4736REV/, 2500);
    expect((await typeBox()).value).not.toMatch(/OLDTYPE/);
    // ... and no preview asks for a new sheet of the archived type, which the server refuses.
    await act(async () => {
      await new Promise((r) => setTimeout(r, 600));
    });
    expect(previews(calls).some((c) => c.body?.includes("OLDTYPE") && c.body.includes('"new_sheet"'))).toBe(false);
  }, 20_000);

  it("stays hidden when no active sheet of it has a free cell", async () => {
    await itemView(routes({ types: [SHEET_TYPE, OLD], sheets: [oldSheet("OLDX-0001", 48), sheet("L4736-0001", 17)] }));
    await userEvent.click(await typeBox());
    const options = (await screen.findAllByRole("option")).map((o) => o.textContent);
    expect(options.join("|")).not.toMatch(/OLDTYPE/);
  });
});

describe("defaults and hints", () => {
  it("with nothing remembered the type that has a sheet with room comes first", async () => {
    const empty = { ...SHEET_TYPE, key: "aaa-empty-type", product_codes: ["AAA-1"], vendor: "Aaa" };
    await itemView(routes({ types: [empty, SHEET_TYPE] }), 1);
    await expectType(/L4736REV/);
  });

  it("choosing cells on a sheet that is too small says so", async () => {
    await itemView(routes({ sheets: [sheet("L4736-0001", 44)] }), 9);
    await userEvent.click(await screen.findByRole("combobox", { name: "Sheet" }));
    await userEvent.click(await screen.findByRole("option", { name: /L4736-0001/ }));
    await userEvent.click(await screen.findByRole("radio", { name: "Choose cells" }));
    // #277: the sheet takes what it holds; the rest goes onto the next sheet.
    expect(await screen.findByText(/has 4 free cells: choose them for the first 4 of 9 labels/)).toBeVisible();
    expect(screen.getByText("0 of 4 cells chosen")).toBeVisible();
  });

  it("the 200 % switch is hidden on a phone while the one page is the tap-size skip view", async () => {
    await itemView(routes(), 1);
    expect(await screen.findByRole("button", { name: "Zoom to 200 %" })).toHaveClass("max-sm:hidden");
  });
});

describe("choosing cells and skipping one", () => {
  it("choosing cells by hand sends exactly those, and printing waits until there are enough", async () => {
    const { calls } = await itemView(routes({ preview: previewFor("L4736-0001", [30, 31], USED_17) }), 2);
    await userEvent.click(await screen.findByRole("radio", { name: "Choose cells" }));
    expect(screen.getByRole("button", { name: "Print onto sheet" })).toBeDisabled();
    expect(screen.getByText("0 of 2 cells chosen")).toBeVisible();
    await userEvent.click(await screen.findByRole("gridcell", { name: /^Cell 30, free/ }));
    await userEvent.click(screen.getByRole("gridcell", { name: /^Cell 31, free/ }));
    expect(await screen.findByText("2 of 2 cells chosen")).toBeVisible();
    await waitFor(() => expect(body(previews(calls).at(-1)!).placements).toEqual([{ sheet: "L4736-0001", cells: [30, 31] }]));
  });

  it("tapping a planned cell in the preview skips it", async () => {
    const answer = (init: RequestInit) => {
      const skip = (JSON.parse(String(init.body)) as { placements: Array<{ skip?: number[] }> }).placements[0]?.skip ?? [];
      return previewFor("L4736-0001", skip.includes(18) ? [19, 20] : [18, 19], USED_17);
    };
    const { calls } = await itemView(routes({ preview: answer }), 2);
    await userEvent.click(await screen.findByRole("gridcell", { name: /^Cell 18, new/ }));
    await waitFor(() => expect(body(previews(calls).at(-1)!).placements).toEqual([{ sheet: "L4736-0001", cells: "first_free", skip: [18] }]));
    expect(await screen.findByRole("gridcell", { name: /^Cell 18, skipped/ })).toBeVisible();
  });
});

describe("asking the server for previews", () => {
  it("changes in quick succession ask for one preview, not one each", async () => {
    const { calls } = await itemView(routes({ preview: previewFor("L4736-0001", [18, 19, 20], USED_17) }), 3);
    await userEvent.click(await screen.findByRole("gridcell", { name: /^Cell 18, new/ }));
    await userEvent.click(screen.getByRole("gridcell", { name: /^Cell 19, new/ }));
    await waitFor(() => expect(body(previews(calls).at(-1)!).placements[0]).toMatchObject({ skip: [18, 19] }));
    // The first preview, and the one for both changes: the one between them never left the browser.
    expect(previews(calls)).toHaveLength(2);
  });
});

describe("the preview", () => {
  it("shows counts, the cells it fills and the zoom", async () => {
    await itemView(routes());
    const preview = await screen.findByRole("region", { name: "Preview" });
    expect(await within(preview).findByText("17 used")).toBeVisible();
    expect(within(preview).getByText("9 printed now")).toBeVisible();
    expect(within(preview).getByText("22 free afterwards")).toBeVisible();
    expect(within(preview).getByText("Cell 18 → Flour 1")).toBeVisible();
    const zoom = within(preview).getByRole("button", { name: "Zoom to 200 %" });
    await userEvent.click(zoom);
    expect(within(preview).getByRole("button", { name: "Whole page" })).toBeVisible();
  });

  it("notes a code-only label, shortened text and a cell in the printer's margin", async () => {
    const page = previewPage("L4736-0001", NEW_9, USED_17);
    page.cells[17] = { ...page.cells[17]!, mapped: true };
    page.cells[18] = { ...page.cells[18]!, truncated: true };
    page.cells[19] = { ...page.cells[19]!, hw_margin: true };
    await itemView(routes({ preview: previewFor("L4736-0001", NEW_9, USED_17, { pages: [page] }) }));
    expect(await screen.findByText("Code only on this sheet type")).toBeVisible();
    expect(screen.getByText(/shortened/)).toBeVisible();
    expect(screen.getByText(/unprintable margin/)).toBeVisible();
  });

  it("lists what was printed before", async () => {
    await itemView(
      routes({ preview: previewFor("L4736-0001", NEW_9, USED_17, { reprint_hints: [{ item_index: 0, sheet_code: "L4736-0002", cell: 5, printed_at: "2026-11-01T08:00:00Z" }] }) }),
      1,
    );
    expect(await screen.findByText(/already printed onto L4736-0002, cell 5/)).toBeVisible();
  });

  it("shows the feed mark entry, the margin ID with its band, and the not-printed warning", async () => {
    await itemView(routes({ preview: previewFor("L4736-0001", NEW_9, USED_17, {}, { feed_mark: true, margin_id: true, margin_band: "bottom" }) }));
    expect(await screen.findByText("Top-edge mark")).toBeVisible();
    expect(screen.getByText("Sheet ID in the bottom margin")).toBeVisible();
    expect(screen.queryByText("Sheet ID not printed, add it by hand")).toBeNull();
  });

  it("warns when no margin can hold the sheet ID", async () => {
    await itemView(routes({ preview: previewFor("L4736-0001", NEW_9, USED_17, {}, { id_not_printed: true }) }));
    expect(await screen.findByText("Sheet ID not printed, add it by hand")).toBeVisible();
  });

  it("draws the PNG of the API as it is, under the cells, and says what the page is", async () => {
    await itemView(routes());
    const grid = await screen.findByRole("grid", { name: /L4736-0001/ });
    expect(grid.querySelector("image")?.getAttribute("href")).toBe("data:image/png;base64,iVBORw0KGgo=");
    expect(screen.getByText("PDF on A4, media type labels, no scaling")).toBeVisible();
  });
});

describe("a picked target belongs to the type it was picked for", () => {
  const OLD = { ...SHEET_TYPE, key: "OLDTYPE", product_codes: ["OLD-1"], vendor: "Old", archived_at: "2026-11-01T00:00:00Z" };
  const oldSheet = (code: string, used: number) => sheet(code, used, { type_key: "OLDTYPE", type_label: "Old OLD-1" });
  const oldRead = (code: string, used: number) =>
    sheetRead(code, { used: Array.from({ length: used }, (_, i) => i + 1) }, { type_key: "OLDTYPE", type_label: "Old OLD-1", used, free: 48 - used });

  function fakeStream() {
    const sources: Array<{ emit: (type: string, printerId: string | null, data: unknown) => void }> = [];
    class FakeEventSource {
      private listeners = new Map<string, Array<(e: MessageEvent) => void>>();
      onopen: (() => void) | null = null;
      onerror: (() => void) | null = null;
      constructor() {
        sources.push(this);
      }
      addEventListener(type: string, fn: (e: MessageEvent) => void) {
        this.listeners.set(type, [...(this.listeners.get(type) ?? []), fn]);
      }
      close() {}
      emit(type: string, printerId: string | null, data: unknown) {
        const payload = JSON.stringify({ channel: "hub", printer_id: printerId, type, ts: "2026-01-01T00:00:00Z", data });
        for (const fn of this.listeners.get(type) ?? []) fn(new MessageEvent(type, { data: payload }));
      }
    }
    vi.stubGlobal("EventSource", FakeEventSource);
    return { stream: () => sources.at(-1)!, ready: () => waitFor(() => expect(sources.length).toBeGreaterThan(0)) };
  }
  const fullEvent = (code: string) => ({ code, free: 0, total: 48, changed: [48], state: "active" });
  const lastPlacements = (calls: Call[]) => body(previews(calls).at(-1)!).placements;

  it("a sheet picked in the remembered type does not follow the type when an event fills the type and the default type takes over", async () => {
    localStorage.setItem(`lph.sheetType.${P}`, "OLDTYPE");
    const { stream, ready } = fakeStream();
    let taken = false;
    const { calls } = await itemView(
      routes({
        types: [SHEET_TYPE, OLD],
        extra: { "GET /api/v1/sheets": () => [oldSheet("OLDX-0001", taken ? 48 : 47), oldSheet("OLDX-0002", taken ? 48 : 47), sheet("L4736-0001", 17)] },
      }),
      1,
    );
    await expectType(/OLDTYPE.*archived/);
    await userEvent.click(await screen.findByRole("combobox", { name: "Sheet" }));
    await userEvent.click(await screen.findByRole("option", { name: /OLDX-0002/ }));
    await waitFor(() => expect(lastPlacements(calls)).toEqual([{ sheet: "OLDX-0002", cells: "first_free" }]));
    await ready();
    taken = true;
    await act(async () => {
      stream().emit("sheet.updated", null, fullEvent("OLDX-0001"));
      stream().emit("sheet.updated", null, fullEvent("OLDX-0002"));
    });
    // The remembered type is full and archived, so it is no longer offered; the default type takes over ...
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Sheet" })).toHaveValue("L4736-0001"), { timeout: 3000 });
    // ... and the target is a sheet of THAT type, never the full sheet of the type that gave way.
    await waitFor(() => expect(lastPlacements(calls)).toEqual([{ sheet: "L4736-0001", cells: "first_free" }]), { timeout: 3000 });
    expect(screen.getByRole("combobox", { name: "Sheet" })).toHaveValue("L4736-0001");
  }, 20_000);

  it("a sheet picked next to the linked sheet does not follow the type when an event fills the type", async () => {
    const { stream, ready } = fakeStream();
    let taken = false;
    const { calls } = await cartView(
      "/cart?sheet=OLDX-0001",
      [LINE("7", 1)],
      routes({
        types: [SHEET_TYPE, OLD],
        extra: {
          "GET /api/v1/sheets": () => [oldSheet("OLDX-0001", taken ? 48 : 47), oldSheet("OLDX-0002", taken ? 48 : 47), sheet("L4736-0001", 17)],
          "GET /api/v1/sheets/OLDX-0001": () => oldRead("OLDX-0001", taken ? 48 : 47),
          "GET /api/v1/sheets/OLDX-0002": () => oldRead("OLDX-0002", taken ? 48 : 47),
        },
      }),
    );
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Sheet" })).toHaveValue("OLDX-0001"));
    await userEvent.click(await screen.findByRole("combobox", { name: "Sheet" }));
    await userEvent.click(await screen.findByRole("option", { name: /OLDX-0002/ }));
    await waitFor(() => expect(lastPlacements(calls)).toEqual([{ sheet: "OLDX-0002", cells: "first_free" }]));
    await ready();
    taken = true;
    await act(async () => {
      stream().emit("sheet.updated", null, fullEvent("OLDX-0001"));
      stream().emit("sheet.updated", null, fullEvent("OLDX-0002"));
    });
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Sheet" })).toHaveValue("L4736-0001"), { timeout: 3000 });
    await waitFor(() => expect(lastPlacements(calls)).toEqual([{ sheet: "L4736-0001", cells: "first_free" }]), { timeout: 3000 });
    expect(screen.getByRole("combobox", { name: "Sheet" })).toHaveValue("L4736-0001");
  }, 20_000);

  it("a picked new sheet on a type that is not archived stays the target while the type does not change", async () => {
    const { stream, ready } = fakeStream();
    let used = 17;
    const { calls } = await itemView(routes({ extra: { "GET /api/v1/sheets": () => [sheet("L4736-0001", used)] } }), 1);
    await userEvent.click(await screen.findByRole("combobox", { name: "Sheet" }));
    await userEvent.click(await screen.findByRole("option", { name: /New .* sheet/ }));
    await waitFor(() => expect(lastPlacements(calls)).toEqual([{ new_sheet: { type: "L4736REV", id_placement: "margin" }, cells: "first_free" }]));
    await ready();
    used = 18;
    await act(async () => {
      stream().emit("sheet.updated", null, { code: "L4736-0001", free: 30, total: 48, changed: [18], state: "active" });
    });
    await act(async () => {
      await new Promise((r) => setTimeout(r, 700));
    });
    expect(lastPlacements(calls)).toEqual([{ new_sheet: { type: "L4736REV", id_placement: "margin" }, cells: "first_free" }]);
    expect((screen.getByRole("combobox", { name: "Sheet" }) as HTMLInputElement).value).toMatch(/New .* sheet/);
  }, 20_000);
});

describe("another computer changes the sheet", () => {
  it("a sheet.updated event on the stream refreshes a preview that names the sheet, other events do not", async () => {
    const sources: Array<{ emit: (type: string, printerId: string | null, data: unknown) => void }> = [];
    class FakeEventSource {
      private listeners = new Map<string, Array<(e: MessageEvent) => void>>();
      onopen: (() => void) | null = null;
      onerror: (() => void) | null = null;
      constructor() {
        sources.push(this);
      }
      addEventListener(type: string, fn: (e: MessageEvent) => void) {
        this.listeners.set(type, [...(this.listeners.get(type) ?? []), fn]);
      }
      close() {}
      emit(type: string, printerId: string | null, data: unknown) {
        const body = JSON.stringify({ channel: "hub", printer_id: printerId, type, ts: "2026-01-01T00:00:00Z", data });
        for (const fn of this.listeners.get(type) ?? []) fn(new MessageEvent(type, { data: body }));
      }
    }
    vi.stubGlobal("EventSource", FakeEventSource);
    const { calls } = await itemView(routes());
    await waitFor(() => expect(previews(calls)).toHaveLength(1));
    await waitFor(() => expect(sources.length).toBeGreaterThan(0));
    const stream = sources.at(-1)!;
    await act(async () => {
      stream.emit("printer.status", P, {});
      stream.emit("sheet.updated", null, { code: "L4736-0099", free: 1, total: 48, changed: [1], state: "active" });
    });
    await act(async () => {
      await new Promise((r) => setTimeout(r, 100));
    });
    expect(previews(calls)).toHaveLength(1);
    await act(async () => {
      stream.emit("sheet.updated", null, { code: "L4736-0001", free: 30, total: 48, changed: [18], state: "active" });
    });
    await waitFor(() => expect(previews(calls)).toHaveLength(2));
  });

  it.each([
    ["plan_changed", "plan_changed", { plan: [{ sheet: "L4736-0001", cells: [18, 19], id_cell: null }] }],
    ["cells_taken", "cells_taken", { cells: [18] }],
  ])("%s keeps the dialog, names what changed, previews again and asks a second time", async (_n, code, detail) => {
    const changed = previewFor("L4736-0001", [19, 20, 21, 22, 23, 24, 25, 26, 27], USED_17.concat(18));
    let previewN = 0;
    let printN = 0;
    const { calls } = await itemView(
      routes({
        preview: () => (++previewN === 1 ? previewFor("L4736-0001", NEW_9, USED_17) : changed),
        print: () =>
          ++printN === 1
            ? conflict(409, code, "Changed.", detail)
            : { batch_id: BATCH, pages: [{ job_id: JOB, sheet_code: "L4736-0001", cells: [19], id_cell: null, margin_id: false, margin_band: null, id_not_printed: false, feed_mark: false }] },
      }),
    );
    await pressPrint();
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("L4736-0001");
    // The dialog stays, the preview is asked again, and nothing was sent a second time yet.
    await waitFor(() => expect(previews(calls)).toHaveLength(2));
    expect(printCalls(calls)).toHaveLength(1);
    const again = await screen.findByRole("button", { name: "Print with the new plan" });
    await waitFor(() => expect(again).toBeEnabled());
    await userEvent.click(again);
    await waitFor(() => expect(printCalls(calls)).toHaveLength(2));
    // The second print carries the NEW plan, never the old expected cells.
    expect(body(printCalls(calls)[0]!).expected_cells).toEqual([{ sheet: "L4736-0001", cells: NEW_9, id_cell: null }]);
    expect(body(printCalls(calls)[1]!).expected_cells).toEqual([{ sheet: "L4736-0001", cells: [19, 20, 21, 22, 23, 24, 25, 26, 27], id_cell: null }]);
    expect(await screen.findByRole("link", { name: /View job/ })).toBeVisible();
  });
});

describe("a scanned code", () => {
  async function scan(text: string, r: Record<string, unknown>) {
    const { setScanDeps } = await import("../../scan/CameraScanner");
    const queue = [{ format: "qr_code" as const, text }];
    setScanDeps({
      createDecoder: async () => ({ engine: "native", decode: vi.fn(async () => queue.shift() ?? null), close: vi.fn() }),
      grabFrame: async () => ({ close() {} }) as unknown as ImageBitmap,
      intervalMs: 5,
    });
    Object.defineProperty(window, "isSecureContext", { value: true, configurable: true });
    HTMLMediaElement.prototype.play = vi.fn(async () => {});
    const stream = { getTracks: () => [{ stop: vi.fn() }] } as unknown as MediaStream;
    Object.defineProperty(navigator, "mediaDevices", { value: { getUserMedia: vi.fn(async () => stream) }, configurable: true });
    const view = await itemView(routes({ sheets: [sheet("L4736-0001", 17), sheet("L4736-0004", 0)], ...{ extra: r } }));
    await userEvent.click(await screen.findByRole("button", { name: "Scan a sheet code" }));
    return view;
  }
  afterEach(async () => (await import("../../scan/CameraScanner")).setScanDeps(null));

  it("selects the sheet when it is of the type, active and has room, and closes the camera", async () => {
    const { calls } = await scan("sheet:L4736-0004", {});
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(body(previews(calls).at(-1)!).placements[0]).toMatchObject({ sheet: "L4736-0004" }));
  });

  it.each([
    ["another type", "sheet:L4736-0020", { "GET /api/v1/sheets/L4736-0020": { ...sheet("L4736-0020", 3), type_key: "other-type", type_label: "Other" } }, /not a sheet of this type/],
    ["a discarded sheet", "sheet:L4736-0021", { "GET /api/v1/sheets/L4736-0021": { ...sheet("L4736-0021", 3), state: "discarded" } }, /is discarded/],
    ["a full sheet", "sheet:L4736-0022", { "GET /api/v1/sheets/L4736-0022": sheet("L4736-0022", 48) }, /no free cell/],
    ["an unknown code", "sheet:L4736-0023", { "GET /api/v1/sheets/L4736-0023": respond(404, { detail: { error_code: "sheet_not_found", error_message: "no" } }) }, /does not know/],
  ])("explains why %s cannot be used and keeps the selection", async (_n, text, extra, words) => {
    const { calls } = await scan(text, extra);
    const note = await screen.findByRole("alert");
    expect(note).toHaveTextContent(words);
    // The scan changed nothing: the sheet that was selected stays.
    await waitFor(() => expect(previews(calls).length).toBeGreaterThan(0));
    expect(body(previews(calls).at(-1)!).placements[0]).toMatchObject({ sheet: "L4736-0001" });
  });
});

describe("a read key", () => {
  it("sees the preview but cannot print, and is told which key it needs", async () => {
    mockApi(routes());
    await renderApp({ path: "/lookup/grocy/7", session: { signed_in: true, scope: "read", source: "api-key", user: null, bootstrap: false, csrf_token: "c" } });
    await screen.findByRole("heading", { level: 2, name: "Print onto a sheet" });
    const button = await screen.findByRole("button", { name: "Print onto sheet" });
    expect(await screen.findByText("Printing needs a print or admin key.")).toBeVisible();
    expect(button).toBeDisabled();
  });
});

describe("not enough free cells", () => {
  const NEED = { free_cells: [9], needed: 10, shortfall: 1 };
  async function overflow() {
    const split = previewFor("L4736-0001", range9(40), USED_17);
    return itemView(
      routes({
        sheets: [sheet("L4736-0001", 39), sheet("L4736-0010", 20), sheet("L4736-0011", 5)],
        preview: (init: RequestInit) => {
          const request = JSON.parse(String(init.body)) as { placements: unknown[] };
          return request.placements.length === 1 && JSON.stringify(request.placements[0]).includes('"first_free"') && !JSON.stringify(request.placements[0]).includes("count")
            ? conflict(409, "insufficient_cells", "Not enough.", NEED)
            : split;
        },
      }),
      10,
    );
  }
  const range9 = (from: number) => Array.from({ length: 9 }, (_, i) => from + i);

  it("says the sheet is too small and offers no split: one run prints one sheet (#277)", async () => {
    const { calls } = await overflow();
    await userEvent.click(await screen.findByRole("combobox", { name: "Sheet" }));
    await userEvent.click(await screen.findByRole("option", { name: /L4736-0001/ }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("only 9 free cells");
    expect(alert).toHaveTextContent("needs 10");
    expect(within(alert).queryByRole("button", { name: /Put the rest/ })).toBeNull();
    expect(previews(calls).every((c) => body(c).placements.length === 1)).toBe(true);
  });

  it("a sheet with enough room takes the whole print", async () => {
    const { calls } = await overflow();
    await userEvent.click(await screen.findByRole("combobox", { name: "Sheet" }));
    await userEvent.click(await screen.findByRole("option", { name: /L4736-0001/ }));
    const sheetBox = screen.getByRole("combobox", { name: "Sheet" }) as HTMLInputElement;
    expect(sheetBox.value).toMatch(/L4736-0001/);
    await userEvent.click(await screen.findByRole("button", { name: "Use L4736-0010 instead (28 free)" }));
    // The best fitting sheet is L4736-0010 from the start, so the last preview alone cannot tell
    // whether the button did anything: the field must have moved off L4736-0001 again.
    await waitFor(() => expect(sheetBox.value).toMatch(/L4736-0010/));
    await waitFor(() => expect(body(previews(calls).at(-1)!).placements).toEqual([{ sheet: "L4736-0010", cells: "first_free" }]));
  });
});

describe("after printing", () => {
  it("links to the jobs and keeps the page's notes: not printed, or the margin band", async () => {
    const pages = [
      { job_id: JOB, sheet_code: "L4736-0001", cells: NEW_9, id_cell: null, margin_id: false, margin_band: null, id_not_printed: true, feed_mark: false },
      { job_id: "55555555-5555-4555-8555-555555555555", sheet_code: "L4736-0006", cells: [1], id_cell: null, margin_id: true, margin_band: "bottom", id_not_printed: false, feed_mark: true },
    ];
    await itemView(routes({ print: { batch_id: BATCH, pages } }));
    await pressPrint();
    const done = await screen.findByRole("status", { name: "Sent to the print queue" });
    const links = within(done).getAllByRole("link", { name: /View job/ });
    expect(links.map((l) => l.getAttribute("href"))).toEqual([`/jobs/${JOB}`, "/jobs/55555555-5555-4555-8555-555555555555"]);
    expect(done).toHaveTextContent("Page 1: L4736-0001, cells 18–26");
    expect(within(done).getByText("Sheet ID not printed, add it by hand")).toBeVisible();
    expect(within(done).getByText("Sheet ID in the bottom margin")).toBeVisible();
  });

  /** Two pages: items 0-4 on L4736-0001, items 5-8 on a new sheet. A request for fewer items gets one page. */
  const twoPages = (init: RequestInit) => {
    const count = (JSON.parse(String(init.body)) as { items: unknown[] }).items.length;
    if (count !== 9) return previewFor("L4736-0001", Array.from({ length: count }, (_, i) => 18 + i), USED_17);
    const first = previewPage("L4736-0001", [18, 19, 20, 21, 22], USED_17);
    const second = previewPage(null, [1, 2, 3, 4], []);
    second.cells = second.cells.map((c) => (c.item_index === null ? c : { ...c, item_index: c.item_index + 5 }));
    return previewFor("L4736-0001", [], [], { pages: [first, second], free_after: [20, 44], expected_cells: [{ sheet: "L4736-0001", cells: [18, 19, 20, 21, 22], id_cell: null }, { sheet: "new", cells: [1, 2, 3, 4], id_cell: null }] });
  };
  // A Response body can be read once, so every route gets a fresh one.
  const interrupted = () => conflict(502, "print_interrupted", "Interrupted.", { batch_id: BATCH, job_ids: [JOB] });

  it("a partial print in the cart previews only the items whose pages were not queued, and says the queued ones left the cart", async () => {
    const { calls } = await cartView("/cart", [LINE("7", 5, "Flour"), LINE("9", 4, "Sugar")], routes({ preview: twoPages, print: interrupted }));
    await pressPrint();
    const note = await screen.findByRole("alert");
    expect(note).toHaveTextContent("5 labels were queued and will print.");
    expect(note).toHaveTextContent("4 labels were not queued. The preview below shows them.");
    expect(note).toHaveTextContent("The queued labels were taken out of the cart. The rest stays in it.");
    expect(note).not.toHaveTextContent("could not be sent");
    expect(within(note).getAllByRole("link", { name: /View job/ }).map((l) => l.getAttribute("href"))).toEqual([`/jobs/${JOB}`]);
    // What is previewed now: the four sugar labels only, never the queued flour.
    await waitFor(() => expect(body(previews(calls).at(-1)!).items).toHaveLength(4));
    const rest = body(previews(calls).at(-1)!).items;
    expect(rest.map((i) => i.lookup?.identifier)).toEqual(["9", "9", "9", "9"]);
    // The cart is the rest: the queued flour is out, the sugar stays.
    expect(JSON.parse(localStorage.getItem(CART_KEY)!)).toEqual([LINE("9", 4, "Sugar")]);
  });

  it("a partial print that queued every label empties the cart but keeps the note and the job links", async () => {
    const JOB2 = "66666666-6666-4666-8666-666666666666";
    const allQueued = () => conflict(502, "print_interrupted", "Interrupted.", { batch_id: BATCH, job_ids: [JOB, JOB2] });
    await cartView("/cart", [LINE("7", 5, "Flour"), LINE("9", 4, "Sugar")], routes({ preview: twoPages, print: allQueued }));
    await pressPrint();
    const note = await screen.findByRole("alert");
    expect(note).toHaveTextContent("9 labels were queued and will print.");
    expect(note).toHaveTextContent("Nothing is left to print.");
    expect(note).toHaveTextContent("The queued labels were taken out of the cart.");
    expect(note).not.toHaveTextContent("The rest stays in it.");
    expect(within(note).getAllByRole("link", { name: /View job/ }).map((l) => l.getAttribute("href"))).toEqual([`/jobs/${JOB}`, `/jobs/${JOB2}`]);
    expect(JSON.parse(localStorage.getItem(CART_KEY)!)).toEqual([]);
    expect(screen.queryByText("The cart is empty.")).toBeNull();
  }, 15000);

  it("after a print that emptied the cart, switching to a tape printer says the cart is empty and offers no print button", async () => {
    const JOB2 = "66666666-6666-4666-8666-666666666666";
    const allQueued = () => conflict(502, "print_interrupted", "Interrupted.", { batch_id: BATCH, job_ids: [JOB, JOB2] });
    await cartView("/cart", [LINE("7", 5, "Flour"), LINE("9", 4, "Sugar")], routes({ preview: twoPages, print: allQueued }));
    await pressPrint();
    await screen.findByRole("alert");
    expect(JSON.parse(localStorage.getItem(CART_KEY)!)).toEqual([]);
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Printer" }), PRINTER_A.id);
    expect(await screen.findByText("The cart is empty.")).toBeVisible();
    expect(screen.queryByRole("button", { name: /^Print \d+ label/ })).toBeNull();
  }, 15000);

  it("a partial print takes exactly the queued copies out of the cart lines", async () => {
    // Two pages again, but the first page holds only 3 of the 5 flour labels: the line keeps 2.
    const threeThenRest = (init: RequestInit) => {
      const count = (JSON.parse(String(init.body)) as { items: unknown[] }).items.length;
      if (count !== 9) return previewFor("L4736-0001", Array.from({ length: count }, (_, i) => 18 + i), USED_17);
      const first = previewPage("L4736-0001", [18, 19, 20], USED_17);
      const second = previewPage(null, [1, 2, 3, 4, 5, 6], []);
      second.cells = second.cells.map((c) => (c.item_index === null ? c : { ...c, item_index: c.item_index + 3 }));
      return previewFor("L4736-0001", [], [], { pages: [first, second], free_after: [20, 44], expected_cells: [{ sheet: "L4736-0001", cells: [18, 19, 20], id_cell: null }, { sheet: "new", cells: [1, 2, 3, 4, 5, 6], id_cell: null }] });
    };
    await cartView("/cart", [LINE("7", 5, "Flour"), LINE("9", 4, "Sugar")], routes({ preview: threeThenRest, print: interrupted }));
    await pressPrint();
    const note = await screen.findByRole("alert");
    expect(note).toHaveTextContent("3 labels were queued and will print.");
    expect(note).toHaveTextContent("6 labels were not queued.");
    expect(JSON.parse(localStorage.getItem(CART_KEY)!)).toEqual([LINE("7", 2, "Flour"), LINE("9", 4, "Sugar")]);
  });

  it("after a partial print, adding another line does not bring the queued labels back into the next preview or print", async () => {
    let printN = 0;
    const accepted = { batch_id: BATCH, pages: [{ job_id: JOB, sheet_code: "L4736-0001", cells: [18, 19, 20, 21, 22], id_cell: null, margin_id: false, margin_band: null, id_not_printed: false, feed_mark: false }] };
    const { calls } = await cartView(
      "/cart",
      [LINE("7", 5, "Flour"), LINE("9", 4, "Sugar")],
      routes({ preview: twoPages, print: () => (++printN === 1 ? interrupted() : accepted) }),
    );
    await pressPrint();
    await screen.findByRole("alert");
    act(() => {
      // Another tab adds a line to whatever the cart holds now.
      localStorage.setItem(CART_KEY, JSON.stringify([...JSON.parse(localStorage.getItem(CART_KEY)!), LINE("11", 1, "Salt")]));
      reloadCart();
    });
    await waitFor(() => expect(body(previews(calls).at(-1)!).items.map((i) => i.lookup?.identifier)).toEqual(["9", "9", "9", "9", "11"]));
    await pressPrint();
    await waitFor(() => expect(printCalls(calls)).toHaveLength(2));
    expect(body(printCalls(calls)[1]!).items.map((i) => i.lookup?.identifier)).toEqual(["9", "9", "9", "9", "11"]);
  });

  it("a partial print in the item view does not mention a cart", async () => {
    const { calls } = await itemView(routes({ preview: twoPages, print: interrupted }));
    await pressPrint();
    const note = await screen.findByRole("alert");
    expect(note).toHaveTextContent("5 labels were queued and will print.");
    expect(note).toHaveTextContent("4 labels were not queued.");
    expect(note).not.toHaveTextContent(/cart/i);
    await waitFor(() => expect(body(previews(calls).at(-1)!).items).toHaveLength(4));
  });

  it("a partial print in the item view still prints only the rest, which it keeps by index", async () => {
    let printN = 0;
    const accepted = { batch_id: BATCH, pages: [{ job_id: JOB, sheet_code: "L4736-0001", cells: [18, 19, 20, 21], id_cell: null, margin_id: false, margin_band: null, id_not_printed: false, feed_mark: false }] };
    const { calls } = await itemView(routes({ preview: twoPages, print: () => (++printN === 1 ? interrupted() : accepted) }));
    await pressPrint();
    await screen.findByRole("alert");
    await waitFor(() => expect(body(previews(calls).at(-1)!).items).toHaveLength(4));
    await pressPrint();
    await waitFor(() => expect(printCalls(calls)).toHaveLength(2));
    expect(body(printCalls(calls)[1]!).items).toHaveLength(4);
  });

  it("printing what is left empties the cart", async () => {
    let printN = 0;
    await cartView(
      "/cart",
      [LINE("7", 5, "Flour"), LINE("9", 4, "Sugar")],
      routes({ preview: twoPages, print: () => (++printN === 1 ? interrupted() : { batch_id: BATCH, pages: [{ job_id: JOB, sheet_code: "L4736-0001", cells: [18, 19, 20, 21], id_cell: null, margin_id: false, margin_band: null, id_not_printed: false, feed_mark: false }] }) }),
    );
    await pressPrint();
    await screen.findByRole("alert");
    await pressPrint();
    expect(await screen.findByRole("status", { name: "Sent to the print queue" })).toBeVisible();
    expect(localStorage.getItem(CART_KEY)).toBe("[]");
  });

  it("printing what is left after a partial print removes the lines of that effort, not one added while it was pending", async () => {
    let printN = 0;
    let release: () => void = () => undefined;
    const gate = new Promise<void>((r) => (release = r));
    const accepted = { batch_id: BATCH, pages: [{ job_id: JOB, sheet_code: "L4736-0001", cells: [18, 19, 20, 21], id_cell: null, margin_id: false, margin_band: null, id_not_printed: false, feed_mark: false }] };
    await cartView(
      "/cart",
      [LINE("7", 5, "Flour"), LINE("9", 4, "Sugar")],
      routes({ preview: twoPages, print: async () => (++printN === 1 ? interrupted() : (await gate, accepted)) }),
    );
    await pressPrint();
    await screen.findByRole("alert");
    expect(JSON.parse(localStorage.getItem(CART_KEY)!)).toEqual([LINE("9", 4, "Sugar")]);
    await pressPrint();
    act(() => {
      localStorage.setItem(CART_KEY, JSON.stringify([LINE("9", 4, "Sugar"), LINE("11", 1)]));
      reloadCart();
    });
    release();
    expect(await screen.findByRole("status", { name: "Sent to the print queue" })).toBeVisible();
    expect(JSON.parse(localStorage.getItem(CART_KEY)!)).toEqual([LINE("11", 1)]);
  });

  it("the cart is cleared even when the page is left while the hub answers", async () => {
    let release: () => void = () => undefined;
    const gate = new Promise<void>((r) => (release = r));
    const { router } = await cartView(
      "/cart",
      [LINE("7", 1)],
      routes({
        extra: {
          [`POST ${PRINT}`]: async () => {
            await gate;
            return { batch_id: BATCH, pages: [{ job_id: JOB, sheet_code: "L4736-0001", cells: [18], id_cell: null, margin_id: false, margin_band: null, id_not_printed: false, feed_mark: false }] };
          },
        },
      }),
    );
    await pressPrint();
    await act(async () => {
      await router.navigate({ to: "/" });
    });
    release();
    await waitFor(() => expect(localStorage.getItem(CART_KEY)).toBe("[]"));
  });
});

describe("failures are words", () => {
  const cases: Array<[string, number, string, Record<string, unknown> | undefined, RegExp]> = [
    ["preview_too_large", 422, "preview_too_large", { pages: 11, max: 10 }, /11 pages.*at most 10/],
    ["content_type_data_mismatch", 422, "content_type_data_mismatch", { item_index: 0, missing_fields: ["title"] }, /Flour.*title/],
    ["integration_unreachable", 502, "integration_unreachable", { item_index: 0 }, /Flour.*did not answer/],
    ["printer_disabled", 409, "printer_disabled", undefined, /switched off/],
    ["printer-unavailable", 503, "printer-unavailable", undefined, /does not know this printer/],
    ["tray_unknown", 409, "tray_unknown", { trays: ["main", "bypass"] }, /tray you chose.*main, bypass/],
    ["tray_unknown without trays", 409, "tray_unknown", { trays: [] }, /reports no trays/],
  ];
  it.each(cases)("a preview answered with %s", async (_n, status, code, detail, words) => {
    await itemView(routes({ preview: conflict(status, code, "Server words.", detail) }));
    expect(await screen.findByRole("alert")).toHaveTextContent(words);
  });

  it("app-lookup-not-found (a problem document) says the item is gone from its app", async () => {
    await itemView(routes({ preview: respond(404, { type: "app-lookup-not-found", title: "Not Found", detail: "grocy 7" }) }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/no longer in its app/);
  });

  it("a network error on the preview is words, not a blank", async () => {
    await itemView(
      routes({
        preview: () => {
          throw new TypeError("network");
        },
      }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("The server cannot be reached.");
  });

  it("a network error on the print is words, and the cart stays", async () => {
    const { fetchMock } = await cartView("/cart", [LINE("7", 1)]);
    const button = await screen.findByRole("button", { name: "Print onto sheet" });
    await waitFor(() => expect(button).toBeEnabled());
    const real = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation(async (input, init) => {
      if (String(input) === PRINT) throw new TypeError("network");
      return real(input, init);
    });
    await userEvent.click(button);
    expect(await screen.findByRole("alert")).toHaveTextContent("The server cannot be reached.");
    expect(JSON.parse(localStorage.getItem(CART_KEY)!)).toHaveLength(1);
  });

  it("a rejected print says why and sends nothing twice", async () => {
    const { calls } = await itemView(routes({ print: conflict(409, "printer_disabled", "Off.") }));
    await pressPrint();
    expect(await screen.findByRole("alert")).toHaveTextContent(/switched off/);
    expect(printCalls(calls)).toHaveLength(1);
  });
});

describe("the cart", () => {
  it("makes one label per copy and clears the cart only after the hub accepted it", async () => {
    const { calls } = await cartView("/cart?sheet=L4736-0001", [LINE("7", 2), LINE("9", 3)], routes({ extra: { "GET /api/v1/lookup/grocy/9": { ...{ app: "grocy", id: "9", name: "Item 9", url: "https://g.example.invalid/9", extra: {} } } } }));
    await waitFor(() => expect(previews(calls).length).toBeGreaterThan(0));
    const request = body(previews(calls)[0]!);
    expect(request.items).toHaveLength(5);
    expect(request.items.map((i) => i.lookup?.identifier)).toEqual(["7", "7", "9", "9", "9"]);
    expect(localStorage.getItem(CART_KEY)).not.toBe("[]");
    await pressPrint();
    expect(await screen.findByRole("status", { name: "Sent to the print queue" })).toBeVisible();
    expect(localStorage.getItem(CART_KEY)).toBe("[]");
  });

  const accepted = { batch_id: BATCH, pages: [{ job_id: JOB, sheet_code: "L4736-0001", cells: [18], id_cell: null, margin_id: false, margin_band: null, id_not_printed: false, feed_mark: false }] };
  /** Another tab changes the cart: storage is written and the page told, as the storage event would. */
  const otherTab = (list: Array<Record<string, unknown>>) =>
    act(() => {
      localStorage.setItem(CART_KEY, JSON.stringify(list));
      reloadCart();
    });

  it("keeps an item another tab added while the print was pending, and removes the submitted ones", async () => {
    let release: () => void = () => undefined;
    const gate = new Promise<void>((r) => (release = r));
    await cartView("/cart", [LINE("7", 1)], routes({ extra: { [`POST ${PRINT}`]: async () => (await gate, accepted) } }));
    await pressPrint();
    otherTab([LINE("7", 1), LINE("9", 2)]);
    release();
    expect(await screen.findByRole("status", { name: "Sent to the print queue" })).toBeVisible();
    expect(JSON.parse(localStorage.getItem(CART_KEY)!)).toEqual([LINE("9", 2)]);
  });

  it("removes only the submitted copies: a line another tab raised keeps the extra copies, the rest stays", async () => {
    let release: () => void = () => undefined;
    const gate = new Promise<void>((r) => (release = r));
    await cartView("/cart", [LINE("7", 1), LINE("8", 1)], routes({ extra: { [`POST ${PRINT}`]: async () => (await gate, accepted) } }));
    await pressPrint();
    otherTab([LINE("7", 3), LINE("8", 1), LINE("9", 1)]);
    release();
    expect(await screen.findByRole("status", { name: "Sent to the print queue" })).toBeVisible();
    expect(JSON.parse(localStorage.getItem(CART_KEY)!)).toEqual([LINE("7", 2), LINE("9", 1)]);
  });

  it("keeps the cart when the print is refused", async () => {
    await cartView("/cart", [LINE("7", 1)], routes({ print: conflict(409, "printer_disabled", "Off.") }));
    await pressPrint();
    await screen.findByRole("alert");
    expect(JSON.parse(localStorage.getItem(CART_KEY)!)).toHaveLength(1);
  });

  it("/cart?sheet=<code> preselects that sheet and its type", async () => {
    const { calls } = await cartView("/cart?sheet=L4736-0001", [LINE("7", 1)], routes({ sheets: [sheet("L4736-0001", 17), sheet("L4736-0002", 3)] }));
    await waitFor(() => expect(previews(calls).length).toBeGreaterThan(0));
    expect(body(previews(calls)[0]!).placements).toEqual([{ sheet: "L4736-0001", cells: "first_free" }]);
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Sheet" })).toHaveValue("L4736-0001"));
  });

  it("an empty cart with a sheet in the link says what to do", async () => {
    await cartView("/cart?sheet=L4736-0001", []);
    expect(await screen.findByText("The cart is empty.")).toBeVisible();
    expect(screen.getByText("Add items to print onto L4736-0001.")).toBeVisible();
  });

  it("an empty cart without a link says only that it is empty", async () => {
    await cartView("/cart", []);
    expect(await screen.findByText("The cart is empty.")).toBeVisible();
    expect(screen.queryByText(/Add items to print onto/)).toBeNull();
  });

  it("tape printers keep the batch print in the cart", async () => {
    await cartView("/cart", [LINE("7", 2)], routes({ printers: [PRINTER_A] }));
    expect(await screen.findByRole("button", { name: "Print 2 labels" })).toBeEnabled();
    expect(screen.queryByRole("heading", { name: "Print onto a sheet" })).toBeNull();
  });
});

describe("one sheet per print run (#277)", () => {
  const SIX = [18, 19, 20, 21, 22, 23];
  const sixOfNine = previewFor("L4736-0001", SIX, USED_17, { placed: 6, remaining: 3 });
  const page = { job_id: JOB, sheet_code: "L4736-0001", cells: SIX, id_cell: null, margin_id: false, margin_band: null, id_not_printed: false, feed_mark: false };
  const printedSix = { batch_id: BATCH, pages: [page], placed: 6, remaining: 3 };

  it("the preview says how many labels fit on the sheet and that the rest stays in the cart", async () => {
    await cartView("/cart", [LINE("7", 5, "Flour"), LINE("9", 4, "Sugar")], routes({ preview: sixOfNine }));
    expect(await screen.findByText("6 of 9 labels fit on this sheet. The rest stays in the cart.")).toBeVisible();
  });

  it("after the print only the placed labels leave the cart; the rest stays for the next run", async () => {
    const { calls } = await cartView("/cart", [LINE("7", 5, "Flour"), LINE("9", 4, "Sugar")], routes({ preview: sixOfNine, print: printedSix }));
    await pressPrint();
    expect(await screen.findByRole("status", { name: "Sent to the print queue" })).toBeVisible();
    // The first six items in cart order printed: all five flour and one sugar.
    await waitFor(() => expect(JSON.parse(localStorage.getItem(CART_KEY)!)).toEqual([LINE("9", 3, "Sugar")]));
    expect(body(printCalls(calls).at(-1)!).items).toHaveLength(9);
  });

  it("without a cart the next preview plans the labels that did not fit", async () => {
    const printed = { ...printedSix, placed: 4, remaining: 5, pages: [{ ...printedSix.pages[0], cells: [18, 19, 20, 21] }] };
    const { calls } = await itemView(routes({ preview: previewFor("L4736-0001", [18, 19, 20, 21], USED_17, { placed: 4, remaining: 5 }), print: printed }), 9);
    await pressPrint();
    await screen.findByRole("status", { name: "Sent to the print queue" });
    await waitFor(() => expect(body(previews(calls).at(-1)!).items).toHaveLength(5));
  });

  it("the cart is not limited: more labels than one request holds send the first 500", async () => {
    const lines = Array.from({ length: 51 }, (_, i) => LINE(String(100 + i), 10, `Item ${i}`));
    const { calls } = await cartView("/cart", lines, routes({ preview: previewFor(null, Array.from({ length: 48 }, (_, i) => i + 1), [], { placed: 48, remaining: 452 }) }));
    await waitFor(() => expect(previews(calls).length).toBeGreaterThan(0));
    expect(body(previews(calls).at(-1)!).items).toHaveLength(500);
    expect(screen.queryByText(/too many for one sheet print/)).toBeNull();
  });
});
