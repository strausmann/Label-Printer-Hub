import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { renderApp } from "../../../test-utils";
import { mockApi, PAGE_PRINTER, PRINTER_A, SHEET_TYPE, pageStatus } from "../../test-api";
import { NEW_9, P, USED_17, body, conflict, expectType, pick, pickType, previewFor, typeBox, reason, routes, sheet } from "./testkit";
import { PREVIEW, itemView, pressPrint, previews, printCalls, resetBetweenTests } from "./SheetSection.kit";
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
    // The mock leaves archived types out unless the request asks for them, as the server does: the print going to the
    // archived type's sheet shows the page asked.
    await expectType(/OLDTYPE.*archived/);
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
