// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { renderApp } from "../../../test-utils";
import { SHEET_TYPE, mockApi, sheetRead, type Call } from "../../test-api";
import { NEW_9, P, USED_17, body, expectType, previewFor, previewPage, routes, sheet } from "./testkit";
import { LINE, cartView, itemView, previews, resetBetweenTests } from "./SheetSection.kit";
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

  it("target flip clears previous choice", async () => {
    // A takes 4 labels at most, B takes 18. With 2 labels the fitting sheet with the fewest free cells (A) is the target.
    const sheets = [sheet("L4736-0001", 44), sheet("L4736-0002", 30)];
    await itemView(routes({ sheets, preview: previewFor("L4736-0001", [30, 31], USED_17) }), 2);
    await userEvent.click(await screen.findByRole("radio", { name: "Choose cells" }));
    await userEvent.click(await screen.findByRole("gridcell", { name: /^Cell 30, free/ }));
    await userEvent.click(screen.getByRole("gridcell", { name: /^Cell 31, free/ }));
    expect(await screen.findByText("2 of 2 cells chosen")).toBeVisible();
    // Six labels do not fit A: the target moves to B by itself, without anyone choosing it.
    fireEvent.change(screen.getByRole("spinbutton", { name: "Copies" }), { target: { value: "6" } });
    expect(await screen.findByRole("combobox", { name: "Sheet" })).toHaveValue("L4736-0002");
    expect(await screen.findByText("0 of 6 cells chosen")).toBeVisible();
    // Back to two labels: the target is A again, and what was chosen on A before is not brought back.
    fireEvent.change(screen.getByRole("spinbutton", { name: "Copies" }), { target: { value: "2" } });
    expect(await screen.findByRole("combobox", { name: "Sheet" })).toHaveValue("L4736-0001");
    expect(await screen.findByText("0 of 2 cells chosen")).toBeVisible();
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

/** A first page whose new cells carry the given labels; `null` takes the item name (Flour). */
function labelled(cells: Array<{ cell: number; purpose: string | null; truncated?: boolean }>) {
  const page = previewPage("L4736-0001", cells.map((c) => c.cell), USED_17);
  for (const [i, c] of cells.entries()) page.cells[c.cell - 1] = { ...page.cells[c.cell - 1]!, item_index: i, purpose: c.purpose, truncated: c.truncated ?? false };
  return previewFor("L4736-0001", cells.map((c) => c.cell), USED_17, { pages: [page] });
}
const TEN = Array.from({ length: 10 }, (_, i) => ({ cell: 18 + i, purpose: "Eggs" }));

describe("the cell list of the preview (#150)", () => {
  it("ten consecutive cells with the same item show as one row with the count", async () => {
    await itemView(routes({ preview: labelled(TEN) }), 10);
    const preview = await screen.findByRole("region", { name: "Preview" });
    expect(await within(preview).findByText("Cells 18–27 → Eggs (10×)")).toBeVisible();
    expect(within(preview).queryByText(/^Cell 18 →/)).toBeNull();
  });

  it("a gap in the cell numbers starts a new row", async () => {
    await itemView(routes({ preview: labelled([18, 19, 21, 22].map((cell) => ({ cell, purpose: "Eggs" }))) }), 4);
    const preview = await screen.findByRole("region", { name: "Preview" });
    expect(await within(preview).findByText("Cells 18–19 → Eggs (2×)")).toBeVisible();
    expect(within(preview).getByText("Cells 21–22 → Eggs (2×)")).toBeVisible();
  });

  it("different items next to each other stay separate rows", async () => {
    await itemView(routes({ preview: labelled([{ cell: 18, purpose: "Eggs" }, { cell: 19, purpose: "Flour" }, { cell: 20, purpose: "Flour" }]) }), 3);
    const preview = await screen.findByRole("region", { name: "Preview" });
    expect(await within(preview).findByText("Cell 18 → Eggs")).toBeVisible();
    expect(within(preview).getByText("Cells 19–20 → Flour (2×)")).toBeVisible();
  });

  it("the shortened-text line is gone", async () => {
    await itemView(routes({ preview: labelled([{ cell: 18, purpose: "Eggs", truncated: true }, { cell: 19, purpose: "Eggs", truncated: true }]) }), 2);
    const preview = await screen.findByRole("region", { name: "Preview" });
    await within(preview).findByText(/Eggs/);
    expect(within(preview).queryByText(/Text shortened to fit/)).toBeNull();
  });

  it("a truncated group carries the shortened mark", async () => {
    const cells = [...TEN.map((c) => ({ ...c, truncated: true })), { cell: 28, purpose: "Milk", truncated: true }];
    await itemView(routes({ preview: labelled(cells) }), 11);
    const preview = await screen.findByRole("region", { name: "Preview" });
    expect(await within(preview).findByText("Cells 18–27 → Eggs (10×, shortened)")).toBeVisible();
    expect(within(preview).getByText("Cell 28 → Milk (shortened)")).toBeVisible();
  });

  it("a row without truncation has no mark, and truncated cells do not join untruncated ones", async () => {
    await itemView(routes({ preview: labelled([{ cell: 18, purpose: "Eggs" }, { cell: 19, purpose: "Eggs" }, { cell: 20, purpose: "Eggs", truncated: true }]) }), 3);
    const preview = await screen.findByRole("region", { name: "Preview" });
    expect(await within(preview).findByText("Cells 18–19 → Eggs (2×)")).toBeVisible();
    expect(within(preview).getByText("Cell 20 → Eggs (shortened)")).toBeVisible();
    expect(within(preview).queryByText(/Cells 18–19.*shortened/)).toBeNull();
  });

  it("thirteen cells that are not next to each other fold into a details with the cell count (#150)", async () => {
    const apart = Array.from({ length: 13 }, (_, i) => ({ cell: 2 + i * 2, purpose: "Eggs" }));
    await itemView(routes({ preview: labelled(apart) }), 13);
    const preview = await screen.findByRole("region", { name: "Preview" });
    const summary = await within(preview).findByText("Show the 13 cells");
    const details = summary.closest("details")!;
    expect(details).not.toHaveAttribute("open");
    expect(within(details).getAllByText(/^Cell \d+ → Eggs$/)).toHaveLength(13);
  });

  it("one run of thirteen consecutive cells stays unfolded as a single row (#150)", async () => {
    const run = Array.from({ length: 13 }, (_, i) => ({ cell: 18 + i, purpose: "Eggs" }));
    await itemView(routes({ preview: labelled(run) }), 13);
    const preview = await screen.findByRole("region", { name: "Preview" });
    expect(await within(preview).findByText("Cells 18–30 → Eggs (13×)")).toBeVisible();
    expect(within(preview).queryByText(/^Show the/)).toBeNull();
  });

  it("a cell left out splits a run into two rows (#150)", async () => {
    const answer = (init: RequestInit) => {
      const skip = (JSON.parse(String(init.body)) as { placements: Array<{ skip?: number[] }> }).placements[0]?.skip ?? [];
      return labelled([18, 19, 20, 21].filter((c) => !skip.includes(c)).map((cell) => ({ cell, purpose: "Eggs" })));
    };
    await itemView(routes({ preview: answer }), 4);
    expect(await screen.findByText("Cells 18–21 → Eggs (4×)")).toBeVisible();
    await userEvent.click(await screen.findByRole("gridcell", { name: /^Cell 19, new/ }));
    expect(await screen.findByText("Cell 18 → Eggs")).toBeVisible();
    expect(screen.getByText("Cells 20–21 → Eggs (2×)")).toBeVisible();
  });

  it("rows never reach across pages (#150)", async () => {
    const first = labelled([46, 47, 48].map((cell) => ({ cell, purpose: "Eggs" })));
    const second = labelled([1, 2].map((cell) => ({ cell, purpose: "Eggs" })));
    const preview = { ...first, pages: [first.pages[0]!, { ...second.pages[0]!, sheet_code: "L4736-0002" }], free_after: [45, 46] };
    await itemView(routes({ preview }), 5);
    const region = await screen.findByRole("region", { name: "Preview" });
    expect(await within(region).findByText("Cells 46–48 → Eggs (3×)")).toBeVisible();
    expect(within(region).getByText("Cells 1–2 → Eggs (2×)")).toBeVisible();
  });

  it("reads in German with the range, the count and the mark", async () => {
    mockApi(routes({ preview: labelled([...TEN, { cell: 28, purpose: "Milch", truncated: true }, { cell: 30, purpose: "Mehl" }]) }));
    await renderApp({ path: "/lookup/grocy/7", language: "de" });
    fireEvent.change(await screen.findByRole("spinbutton", { name: "Kopien" }), { target: { value: "12" } });
    const preview = await screen.findByRole("region", { name: "Vorschau" });
    expect(await within(preview).findByText("Zellen 18–27 → Eggs (10×)")).toBeVisible();
    expect(within(preview).getByText("Zelle 28 → Milch (gekürzt)")).toBeVisible();
    expect(within(preview).getByText("Zelle 30 → Mehl")).toBeVisible();
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
    expect(screen.getByText(/unprintable margin/)).toBeVisible();
    expect(screen.queryByText(/Text shortened to fit/)).toBeNull();
  });

  it("lists what was printed before", async () => {
    await itemView(
      routes({ preview: previewFor("L4736-0001", NEW_9, USED_17, {
        reprint_hints: [{ item_index: 0, sheet_code: "L4736-0002", cell: 5, printed_at: "2026-11-01T08:00:00Z" }],
        reprint_totals: [{ item_index: 0, total: 1, sheets: { "L4736-0002": 1 } }],
      }) }),
      1,
    );
    expect(await screen.findByText(/^Flour: printed before on L4736-0002 on .*2026, cell 5$/)).toBeVisible();
  });

  it("sums up ten copies of an item printed five times before in one line, with the details folded (#340)", async () => {
    // The server lists the earlier prints once, on the first copy (backend test_preview_reprint_hints_once_per_item_not_per_copy).
    const earlier = [2, 3, 4, 5, 6].map((cell) => ({ item_index: 0, sheet_code: "L4736-0001", cell, printed_at: "2026-11-14T08:00:00Z" }));
    const fresh = [18, 19, 20, 21, 22, 23, 24, 25, 26, 27];
    await itemView(routes({ preview: previewFor("L4736-0001", fresh, USED_17, { reprint_hints: earlier, reprint_totals: [{ item_index: 0, total: 5, sheets: { "L4736-0001": 5 } }] }) }), 10);
    const preview = await screen.findByRole("region", { name: "Preview" });
    const lines = await within(preview).findAllByText(/printed before/);
    expect(lines).toHaveLength(1);
    expect(lines[0]).toHaveTextContent(/^Flour: printed before 5× on L4736-0001 on .*2026, cells 2–6$/);
    expect(within(preview).queryByText(/already printed/)).toBeNull();
  });

  it("opens a table of the earlier prints of an item on several sheets (#340)", async () => {
    const hints = [
      { item_index: 0, sheet_code: "L4736-0001", cell: 2, printed_at: "2026-11-14T08:00:00Z" },
      { item_index: 0, sheet_code: "L4736-0001", cell: 3, printed_at: "2026-11-14T08:00:00Z" },
      { item_index: 0, sheet_code: "L4736-0002", cell: 9, printed_at: "2026-11-01T08:00:00Z" },
    ];
    await itemView(routes({ preview: previewFor("L4736-0001", NEW_9, USED_17, { reprint_hints: hints, reprint_totals: [{ item_index: 0, total: 3, sheets: { "L4736-0001": 2, "L4736-0002": 1 } }] }) }), 1);
    const preview = await screen.findByRole("region", { name: "Preview" });
    const summary = await within(preview).findByText(/^Flour: printed before 3× on 2 sheets, last on .*2026$/);
    await userEvent.click(summary);
    const table = within(preview).getByRole("table", { name: "Earlier prints of Flour" });
    const rows = within(table).getAllByRole("row").map((r) => r.textContent);
    expect(rows).toHaveLength(3);
    expect(rows[1]).toMatch(/^L4736-0001.*2026 ?2–3 ?2$/);
    expect(rows[2]).toMatch(/^L4736-0002.*2026 ?9 ?1$/);
  });

  it("says the true count of eight earlier prints when only the newest five are listed (#340)", async () => {
    const listed = [2, 3, 4, 5, 6].map((cell) => ({ item_index: 0, sheet_code: "L4736-0001", cell, printed_at: "2026-11-14T08:00:00Z" }));
    const totals = [{ item_index: 0, total: 8, sheets: { "L4736-0001": 8 } }];
    await itemView(routes({ preview: previewFor("L4736-0001", NEW_9, USED_17, { reprint_hints: listed, reprint_totals: totals }) }), 1);
    const preview = await screen.findByRole("region", { name: "Preview" });
    const summary = await within(preview).findByText("Flour: printed before 8× on L4736-0001, the last 5 listed");
    expect(within(preview).queryByText(/5× on/)).toBeNull();
    await userEvent.click(summary);
    const rows = within(within(preview).getByRole("table", { name: "Earlier prints of Flour" })).getAllByRole("row").map((r) => r.textContent);
    expect(rows).toHaveLength(2);
    expect(rows[1]).toMatch(/^L4736-0001.*2026 ?2–6 ?5$/);
  });

  it("says the true count over several sheets when the list is cut (#340)", async () => {
    const listed = [2, 3, 4, 5, 6].map((cell) => ({ item_index: 0, sheet_code: "L4736-0001", cell, printed_at: "2026-11-14T08:00:00Z" }));
    const totals = [{ item_index: 0, total: 9, sheets: { "L4736-0001": 6, "L4736-0002": 3 } }];
    await itemView(routes({ preview: previewFor("L4736-0001", NEW_9, USED_17, { reprint_hints: listed, reprint_totals: totals }) }), 1);
    expect(await screen.findByText("Flour: printed before 9× on 2 sheets, the last 5 listed")).toBeVisible();
  });

  it("too many previews at once shows a readable wait, then the preview replaces it (#339)", async () => {
    let answers = 0;
    const preview = () =>
      ++answers === 1
        ? new Response(JSON.stringify({ detail: { error_code: "too-many-previews", error_message: "Busy.", retry_after_seconds: 1 } }), {
            status: 429,
            headers: { "Content-Type": "application/json", "Retry-After": "1" },
          })
        : new Response(JSON.stringify(previewFor("L4736-0001", NEW_9, USED_17)), { status: 200, headers: { "Content-Type": "application/json" } });
    const { calls } = await itemView(routes({ preview }));
    expect(await screen.findByText("Too many previews at once. The preview updates in a moment.")).toBeVisible();
    expect(screen.queryByText(/too-many-previews/)).toBeNull();
    expect(await screen.findByText("9 printed now", undefined, { timeout: 5000 })).toBeVisible();
    expect(screen.queryByText(/Too many previews/)).toBeNull();
    expect(previews(calls)).toHaveLength(2);
  });

  it("after the last automatic try, too many previews says to try again and a button asks again (#339)", async () => {
    let busy = true;
    const preview = () =>
      busy
        ? new Response(JSON.stringify({ detail: { error_code: "too-many-previews", error_message: "Busy.", retry_after_seconds: 1 } }), {
            status: 429,
            headers: { "Content-Type": "application/json", "Retry-After": "1" },
          })
        : new Response(JSON.stringify(previewFor("L4736-0001", NEW_9, USED_17)), { status: 200, headers: { "Content-Type": "application/json" } });
    const { calls } = await itemView(routes({ preview }));
    const alert = await screen.findByRole("alert", undefined, { timeout: 9000 });
    expect(alert).toHaveTextContent("Too many previews right now. Try again in a moment.");
    // The first ask and five automatic ones, then it stops.
    expect(previews(calls)).toHaveLength(6);
    busy = false;
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("9 printed now")).toBeVisible();
    expect(screen.queryByText(/Too many previews/)).toBeNull();
  }, 20_000);

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

  it("a back-side sheet shows no \"Sheet ID not printed\" warning", async () => {
    // #350: the server plans no margin ID for a sheet whose code goes on the back, and says so.
    await itemView(routes({ preview: previewFor("L4736-0001", NEW_9, USED_17, {}, { id_not_printed: false, margin_id: false }) }));
    await screen.findByRole("grid", { name: /L4736-0001/ });
    expect(screen.queryByText("Sheet ID not printed, add it by hand")).toBeNull();
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
    await waitFor(() => expect(lastPlacements(calls)).toEqual([{ new_sheet: { type: "L4736REV" }, cells: "first_free" }]));
    await ready();
    used = 18;
    await act(async () => {
      stream().emit("sheet.updated", null, { code: "L4736-0001", free: 30, total: 48, changed: [18], state: "active" });
    });
    await act(async () => {
      await new Promise((r) => setTimeout(r, 700));
    });
    expect(lastPlacements(calls)).toEqual([{ new_sheet: { type: "L4736REV" }, cells: "first_free" }]);
    expect((screen.getByRole("combobox", { name: "Sheet" }) as HTMLInputElement).value).toMatch(/New .* sheet/);
  }, 20_000);
});
