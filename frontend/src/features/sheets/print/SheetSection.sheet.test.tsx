import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderApp } from "../../../test-utils";
import { CART_KEY, reloadCart } from "../../lookup/cart";
import { mockApi, PRINTER_A, respond } from "../../test-api";
import { SHEET_PREVIEW_KEY } from "../keys";
import { BATCH, JOB, NEW_9, P, USED_17, body, conflict, previewFor, routes, sheet } from "./testkit";
import { LINE, PRINT, cartView, itemView, pressPrint, previews, printCalls, resetBetweenTests } from "./SheetSection.kit";
import type * as Debounced from "./useDebounced";

// The preview is asked for 400 ms after the last change (PREVIEW_DEBOUNCE_MS); SheetSection.debounce.test.tsx holds the
// test of that wait. Here it is cut to 20 ms, so a test does not sit through it on every preview and the default findBy
// window is enough.
vi.mock("./useDebounced", async (importOriginal) => {
  const real = await importOriginal<typeof Debounced>();
  return { useDebounced: <T,>(value: T, ms: number) => real.useDebounced(value, Math.min(ms, 20)) };
});

// Each test boots the whole app and clicks re-render it, so the busiest ones take a few seconds on a loaded runner;
// the per-test limit is widened for this file only (vi.setConfig is scoped to the file).
vi.setConfig({ testTimeout: 15_000 });
resetBetweenTests();

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
    const { calls, queryClient } = await itemView(routes());
    // The request is complete once the item, the copies, the tray and the sheet are known; which of their
    // queries answers first decides how many previews it takes to get there, so wait for the content, not a count.
    await waitFor(() => expect(body(previews(calls).at(-1)!)).toMatchObject({ tray: "main", placements: [{ sheet: "L4736-0001" }] }));
    expect(body(previews(calls).at(-1)!).items).toHaveLength(9);
    const sheetPreviews = () => queryClient.getQueryCache().findAll({ queryKey: [SHEET_PREVIEW_KEY] });
    await waitFor(() => expect(sheetPreviews().every((q) => q.state.fetchStatus === "idle")).toBe(true));
    await waitFor(() => expect(sources.length).toBeGreaterThan(0));
    const stream = sources.at(-1)!;
    const before = previews(calls).length;
    act(() => {
      stream.emit("printer.status", P, {});
      stream.emit("sheet.updated", null, { code: "L4736-0099", free: 1, total: 48, changed: [1], state: "active" });
    });
    // The handler invalidates synchronously, so "the preview was not asked again" is a state to read now, not a
    // wait for a request that might come late.
    expect(sheetPreviews().some((q) => q.state.isInvalidated || q.state.fetchStatus !== "idle")).toBe(false);
    act(() => {
      stream.emit("sheet.updated", null, { code: "L4736-0001", free: 30, total: 48, changed: [18], state: "active" });
    });
    await waitFor(() => expect(previews(calls)).toHaveLength(before + 1));
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

  it("offers other sheets only for the sheet that was asked about, not the one before it", async () => {
    // Picking a sheet re-asks for the preview after the debounce. Until then the refusal on screen is the one for the sheet
    // before, and the alert offered that sheet's alternatives under the new sheet's name. A press on one of those buttons was
    // lost when the debounce took the alert away under it: the flaky "takes the whole print" below (expected L4736-0010, got
    // L4736-0001).
    const { calls } = await overflow();
    const offeredFor: string[] = [];
    const watch = new MutationObserver(() => {
      if (screen.queryByRole("button", { name: "Use L4736-0010 instead (28 free)" }))
        offeredFor.push(String((body(previews(calls).at(-1)!).placements[0] as { sheet?: string }).sheet));
    });
    watch.observe(document.body, { childList: true, subtree: true, characterData: true });
    try {
      await userEvent.click(await screen.findByRole("combobox", { name: "Sheet" }));
      await userEvent.click(await screen.findByRole("option", { name: /L4736-0001/ }));
      await screen.findByRole("button", { name: "Use L4736-0010 instead (28 free)" });
    } finally {
      watch.disconnect();
    }
    expect(offeredFor.length).toBeGreaterThan(0);
    expect(new Set(offeredFor)).toEqual(new Set(["L4736-0001"]));
  });

  it("a sheet with enough room takes the whole print", async () => {
    const { calls } = await overflow();
    await userEvent.click(await screen.findByRole("combobox", { name: "Sheet" }));
    await userEvent.click(await screen.findByRole("option", { name: /L4736-0001/ }));
    const sheetBox = screen.getByRole("combobox", { name: "Sheet" }) as HTMLInputElement;
    expect(sheetBox.value).toMatch(/L4736-0001/);
    // Leave the field first. With the menu opening on focus, a late re-render could open the list again while
    // the field still has focus, and the press on the button below would then only close that list (CI run
    // 43349587904 announced the options twice and kept L4736-0001). Without focus it cannot open.
    act(() => sheetBox.blur());
    expect(screen.queryByRole("listbox")).toBeNull();
    await userEvent.click(await screen.findByRole("button", { name: "Use L4736-0010 instead (28 free)" }));
    // The best fitting sheet is L4736-0010 from the start, so the last preview alone cannot tell
    // whether the button did anything: the field must have moved off L4736-0001 again.
    await waitFor(() => expect(sheetBox.value).toMatch(/L4736-0010/));
    await waitFor(() => expect(body(previews(calls).at(-1)!).placements).toEqual([{ sheet: "L4736-0010", cells: "first_free" }]));
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
