// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { CART_KEY, reloadCart } from "../../lookup/cart";
import { PRINTER_A, respond } from "../../test-api";
import { BATCH, JOB, NEW_9, USED_17, body, conflict, previewFor, previewPage, routes } from "./testkit";
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
