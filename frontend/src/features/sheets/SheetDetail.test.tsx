import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderApp, SIGNED_IN } from "../../test-utils";
import { apiErrorBody, mockApi, respond, sheetRead, type Call } from "../test-api";
import { sheetKey } from "./keys";
import type { SheetRead } from "./api";

const PRINT_SESSION = { ...SIGNED_IN, scope: "print" as const };
const READ_SESSION = { ...SIGNED_IN, scope: "read" as const };
const CODE = "L4736-0001";
const PATH = `/api/v1/sheets/${CODE}`;

// Whole-app renders with grids of 48 cells: under coverage and a loaded runner they need more than 5 s.
vi.setConfig({ testTimeout: 15_000 });
afterEach(() => vi.unstubAllGlobals());

/** Gives the listed cells the marks the server writes for a hand-marked cell, with a purpose. */
function byHand(sheet: SheetRead, cells: number[], purpose: (n: number) => string | null = (n) => `item ${n}`): SheetRead {
  return {
    ...sheet,
    cells: sheet.cells.map((c) => (cells.includes(c.cell) ? { ...c, source: "manual", marked_by_hand: true, purpose: purpose(c.cell) } : c)),
  };
}

const posts = (calls: Call[]) => calls.filter((c) => c.method === "POST");
const body = (call: Call) => JSON.parse(call.body ?? "null");
const cell = (n: number) => screen.getByRole("gridcell", { name: new RegExp(`^Cell ${n},`) });

async function open(sheet: SheetRead, extra: Record<string, unknown> = {}, session: typeof PRINT_SESSION | typeof READ_SESSION = PRINT_SESSION, path = `/sheets/${CODE}`) {
  const api = mockApi({ [`GET ${PATH}`]: sheet, ...extra });
  const app = await renderApp({ path, session });
  await screen.findByRole("heading", { level: 1, name: sheet.code });
  return { ...api, ...app };
}

describe("the sheet detail page", () => {
  it("id cell from flag", async () => {
    const base = sheetRead(CODE, { used: [1, 2] }, { id_placement: "cell", id_printed: true });
    // Both cells are written by the hub; only the flagged one holds the ID label.
    await open({ ...base, cells: base.cells.map((c) => ({ ...c, source: "hub", is_id_cell: c.cell === 1 })) });
    expect(cell(1)).toHaveAccessibleName(/sheet ID/);
    expect(cell(2)).not.toHaveAccessibleName(/sheet ID/);
  });

  it("no cell is called the ID cell when the flag is off, whatever the placement says", async () => {
    const base = sheetRead(CODE, { used: [1] }, { id_placement: "cell", id_printed: false });
    await open({ ...base, cells: base.cells.map((c) => ({ ...c, source: "hub", is_id_cell: false })) });
    expect(cell(1)).not.toHaveAccessibleName(/sheet ID/);
  });

  it("is reachable under both paths (the QR code prints /sheet/<code>)", async () => {
    await open(sheetRead(CODE), {}, PRINT_SESSION, `/sheet/${CODE}`);
    expect(screen.getByRole("grid", { name: CODE })).toBeVisible();
  });

  it("says plainly that an unknown code does not exist", async () => {
    mockApi({ "GET /api/v1/sheets/L4736-9999": () => respond(404, apiErrorBody("sheet_not_found", "Sheet not found.")) });
    await renderApp({ path: "/sheets/L4736-9999", session: PRINT_SESSION });
    expect(await screen.findByText("That sheet does not exist.")).toBeVisible();
    expect(screen.getByRole("link", { name: "Back to the sheets" })).toHaveAttribute("href", "/sheets");
  });

  it("names the discard date and that the ID is not used again, and offers no actions", async () => {
    await open(sheetRead(CODE, { used: [1] }, { state: "discarded", discarded_at: "2026-11-02T12:00:00Z" }));
    expect(screen.getByText("Discarded on Nov 2, 2026, this ID is not used again.")).toBeVisible();
    for (const name of [/Mark cells as used/, /Un-mark cells/, /Discard sheet/, /Print onto this sheet/]) {
      expect(screen.queryByRole("button", { name })).toBeNull();
      expect(screen.queryByRole("link", { name })).toBeNull();
    }
  });

  it("a discarded sheet with unconfirmed cells offers no resolve buttons (#212)", async () => {
    await open(sheetRead(CODE, { unconfirmed: [4] }, { state: "discarded", discarded_at: "2026-11-02T12:00:00Z" }));
    expect(screen.queryByRole("button", { name: /^Printed/ })).toBeNull();
  });

  it("says 'Sheet ID not printed yet' for a margin sheet whose ID is not printed, and not for a manual one", async () => {
    const { unmount } = await open(sheetRead(CODE, { used: [1] }, { id_placement: "margin", id_printed: false }));
    expect(screen.getByText("Sheet ID not printed yet")).toBeVisible();
    expect(screen.queryByText(/Resolve the unconfirmed cells first/)).toBeNull();
    unmount();
    await open(sheetRead(CODE, { used: [1] }, { id_placement: "manual", id_printed: false }));
    expect(screen.queryByText("Sheet ID not printed yet")).toBeNull();
  });

  it("adds that the ID waits for the unconfirmed cells when there are some", async () => {
    await open(sheetRead(CODE, { unconfirmed: [2, 3] }, { id_placement: "cell", id_printed: false }));
    expect(screen.getByText("Sheet ID not printed yet")).toBeVisible();
    expect(screen.getByText("Resolve the unconfirmed cells first; the sheet ID waits for them")).toBeVisible();
  });

  it("shows whether the feed mark is printed", async () => {
    const { unmount } = await open(sheetRead(CODE, { used: [1] }, { feed_mark_printed: true }));
    expect(screen.getByText("Feed mark printed")).toBeVisible();
    expect(screen.getByText("Feed mark printed").parentElement).toHaveTextContent("Feed mark printed: yes");
    unmount();
    await open(sheetRead(CODE, { used: [1] }, { feed_mark_printed: false }));
    expect(screen.getByText("Feed mark printed").parentElement).toHaveTextContent("Feed mark printed: no");
  });

  it("links to the cart with the sheet code", async () => {
    await open(sheetRead(CODE));
    expect(screen.getByRole("link", { name: "Print onto this sheet" })).toHaveAttribute("href", "/cart?sheet=L4736-0001");
  });

  it("offers a read key nothing to change", async () => {
    await open(sheetRead(CODE, { used: [1], unconfirmed: [2] }), {}, READ_SESSION);
    expect(screen.queryByRole("button", { name: /Mark cells|Un-mark|Discard|^Printed/ })).toBeNull();
    expect(screen.queryByRole("link", { name: "Print onto this sheet" })).toBeNull();
  });

  it("lists 'Cell n → purpose · source' with the source in words", async () => {
    const sheet = byHand(sheetRead(CODE, { used: [1, 2, 3, 4] }), [1]);
    sheet.cells[1] = { ...sheet.cells[1]!, source: "grocy", purpose: "flour 1 kg" };
    sheet.cells[2] = { ...sheet.cells[2]!, source: "hub", purpose: null, is_id_cell: true };
    sheet.cells[3] = { ...sheet.cells[3]!, source: "kept-app", purpose: "tag" };
    await open(sheet);
    const list = screen.getByRole("list", { name: "Cells in use" });
    expect(within(list).getByText("Cell 1 → item 1 · marked by hand")).toBeVisible();
    expect(within(list).getByText("Cell 2 → flour 1 kg · Grocy")).toBeVisible();
    expect(within(list).getByText("Cell 3 → no purpose · Sheet ID")).toBeVisible();
    expect(within(list).getByText("Cell 4 → tag · kept-app")).toBeVisible();
  });

  it("reads the purpose of a cell on focus and on tap, not only on hover", async () => {
    await open(byHand(sheetRead(CODE, { used: [1, 2] }), [1, 2]));
    expect(screen.getByRole("status", { name: "Selected cell" })).toBeEmptyDOMElement();
    await userEvent.click(cell(2));
    expect(screen.getByRole("status", { name: "Selected cell" })).toHaveTextContent("Cell 2 → item 2 · marked by hand");
    act(() => cell(1).focus());
    expect(screen.getByRole("status", { name: "Selected cell" })).toHaveTextContent("Cell 1 → item 1 · marked by hand");
    await userEvent.click(cell(30));
    expect(screen.getByRole("status", { name: "Selected cell" })).toHaveTextContent("Cell 30 is free");
  });

  it("has one live region for the cell line, not a status inside another live region", async () => {
    await open(byHand(sheetRead(CODE, { used: [1] }), [1]));
    await userEvent.click(cell(1));
    const status = screen.getByRole("status", { name: "Selected cell" });
    expect(status.parentElement?.closest("[aria-live]")).toBeNull();
  });

  it("shows the last-used time as text, with no hover-only title", async () => {
    await open(sheetRead(CODE, { used: [1] }));
    const time = screen.getByText("Last used").closest("div")!.querySelector("time")!;
    expect(time).toHaveTextContent(/2026/);
    expect(time).not.toHaveAttribute("title");
  });

  it("re-renders a newly reserved cell with the clock glyph when the sheet changes live", async () => {
    let sheet = sheetRead(CODE, { used: [1] });
    const { queryClient } = await open(sheet, { [`GET ${PATH}`]: () => sheet });
    expect(cell(7).querySelector("[data-marker=clock]")).toBeNull();
    sheet = sheetRead(CODE, { used: [1], reserved: [7] });
    await act(async () => {
      await queryClient.invalidateQueries({ queryKey: sheetKey(CODE) });
    });
    await waitFor(() => expect(cell(7).querySelector("[data-marker=clock]")).not.toBeNull());
    expect(cell(7)).toHaveAttribute("aria-label", expect.stringContaining("reserved"));
  });
});

describe("marking cells as used", () => {
  const fresh = () => sheetRead(CODE, { used: [1, 2, 3] });

  it("sends the chosen cells with the purpose and goes back to the overview", async () => {
    const { calls } = await open(fresh(), { [`POST ${PATH}/cells/mark`]: sheetRead(CODE, { used: [1, 2, 3, 20, 21] }) });
    await userEvent.click(screen.getByRole("button", { name: "Mark cells as used" }));
    await userEvent.click(cell(20));
    await userEvent.click(cell(21));
    await userEvent.click(cell(1)); // used: cannot be chosen
    const input = screen.getByRole("textbox", { name: "Purpose (optional)" });
    expect(input).toHaveAttribute("maxlength", "120");
    await userEvent.type(input, "flour");
    await userEvent.click(screen.getByRole("button", { name: "Mark 2 cells as used" }));
    await waitFor(() => expect(posts(calls)).toHaveLength(1));
    expect(body(posts(calls)[0]!)).toEqual({ cells: [{ cell: 20, purpose: "flour" }, { cell: 21, purpose: "flour" }] });
    await waitFor(() => expect(screen.queryByRole("button", { name: /^Mark \d+ cells? as used$/ })).toBeNull());
    expect(screen.getByRole("button", { name: "Mark cells as used" })).toBeVisible();
    expect(screen.getByText("5 of 48 used")).toBeVisible();
  });

  it("leaves the purpose out when none was typed", async () => {
    const { calls } = await open(fresh(), { [`POST ${PATH}/cells/mark`]: sheetRead(CODE, { used: [1, 2, 3, 20] }) });
    await userEvent.click(screen.getByRole("button", { name: "Mark cells as used" }));
    await userEvent.click(cell(20));
    await userEvent.click(screen.getByRole("button", { name: "Mark 1 cell as used" }));
    await waitFor(() => expect(posts(calls)).toHaveLength(1));
    expect(body(posts(calls)[0]!)).toEqual({ cells: [{ cell: 20 }] });
  });

  it("shows cells_taken as words, keeps the choice and reloads the sheet", async () => {
    const { calls } = await open(fresh(), {
      [`POST ${PATH}/cells/mark`]: () => respond(409, apiErrorBody("cells_taken", "Some cells are not free.", { cells: [20] })),
    });
    await userEvent.click(screen.getByRole("button", { name: "Mark cells as used" }));
    await userEvent.click(cell(20));
    const before = calls.filter((c) => c.method === "GET" && c.path === PATH).length;
    await userEvent.click(screen.getByRole("button", { name: "Mark 1 cell as used" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("One of those cells is already in use.");
    expect(screen.getByRole("button", { name: "Mark 1 cell as used" })).toBeVisible();
    await waitFor(() => expect(calls.filter((c) => c.method === "GET" && c.path === PATH).length).toBeGreaterThan(before));
  });

  it("shows a network error as words, not as a code", async () => {
    await open(fresh(), {
      [`POST ${PATH}/cells/mark`]: () => {
        throw new TypeError("Failed to fetch");
      },
    });
    await userEvent.click(screen.getByRole("button", { name: "Mark cells as used" }));
    await userEvent.click(cell(20));
    await userEvent.click(screen.getByRole("button", { name: "Mark 1 cell as used" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The server cannot be reached.");
  });

  it("says 'chosen' for a chosen cell, as the grid draws it, and not 'free'", async () => {
    await open(fresh());
    await userEvent.click(screen.getByRole("button", { name: "Mark cells as used" }));
    await userEvent.click(cell(20));
    expect(screen.getByRole("status", { name: "Selected cell" })).toHaveTextContent("Cell 20 is chosen");
    await userEvent.click(cell(20)); // taken back: free again
    expect(screen.getByRole("status", { name: "Selected cell" })).toHaveTextContent("Cell 20 is free");
  });

  it("leaves marking without sending anything", async () => {
    const { calls } = await open(fresh());
    await userEvent.click(screen.getByRole("button", { name: "Mark cells as used" }));
    await userEvent.click(cell(20));
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getByRole("button", { name: "Mark cells as used" })).toBeVisible();
    expect(posts(calls)).toHaveLength(0);
  });
});

describe("un-marking cells", () => {
  const mixed = () => {
    const sheet = byHand(sheetRead(CODE, { used: [1, 2, 3, 4] }), [1, 2]);
    return sheet;
  };

  it("offers only the cells that were marked by hand", async () => {
    await open(mixed());
    await userEvent.click(screen.getByRole("button", { name: "Un-mark cells" }));
    expect(cell(1)).not.toHaveAttribute("aria-disabled");
    expect(cell(2)).not.toHaveAttribute("aria-disabled");
    expect(cell(3)).toHaveAttribute("aria-disabled", "true"); // printed by a job
    expect(cell(4)).toHaveAttribute("aria-disabled", "true");
    expect(cell(30)).toHaveAttribute("aria-disabled", "true"); // free
    await userEvent.click(cell(3));
    expect(screen.getByRole("button", { name: "Un-mark 0 cells" })).toBeDisabled();
  });

  it("says 'chosen' for a cell chosen to be un-marked, which the grid draws free", async () => {
    await open(mixed());
    await userEvent.click(screen.getByRole("button", { name: "Un-mark cells" }));
    await userEvent.click(cell(1));
    expect(screen.getByRole("status", { name: "Selected cell" })).toHaveTextContent("Cell 1 is chosen");
  });

  it("sends the chosen cells and returns to the overview", async () => {
    const { calls } = await open(mixed(), { [`POST ${PATH}/cells/unmark`]: byHand(sheetRead(CODE, { used: [2, 3, 4] }), [2]) });
    await userEvent.click(screen.getByRole("button", { name: "Un-mark cells" }));
    await userEvent.click(cell(1));
    await userEvent.click(screen.getByRole("button", { name: "Un-mark 1 cell" }));
    await waitFor(() => expect(posts(calls)).toHaveLength(1));
    expect(body(posts(calls)[0]!)).toEqual({ cells: [1] });
    await waitFor(() => expect(screen.getByRole("button", { name: "Un-mark cells" })).toBeVisible());
  });

  it("shows cells_not_marked_by_hand as words", async () => {
    await open(mixed(), {
      [`POST ${PATH}/cells/unmark`]: () => respond(409, apiErrorBody("cells_not_marked_by_hand", "Some cells were not marked by hand.", { cells: [1] })),
    });
    await userEvent.click(screen.getByRole("button", { name: "Un-mark cells" }));
    await userEvent.click(cell(1));
    await userEvent.click(screen.getByRole("button", { name: "Un-mark 1 cell" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Only cells that were marked by hand can be un-marked.");
  });

  it("shows a network error as words", async () => {
    await open(mixed(), {
      [`POST ${PATH}/cells/unmark`]: () => {
        throw new TypeError("Failed to fetch");
      },
    });
    await userEvent.click(screen.getByRole("button", { name: "Un-mark cells" }));
    await userEvent.click(cell(1));
    await userEvent.click(screen.getByRole("button", { name: "Un-mark 1 cell" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The server cannot be reached.");
  });

  it("is not offered when no cell was marked by hand", async () => {
    await open(sheetRead(CODE, { used: [1, 2] }));
    expect(screen.queryByRole("button", { name: "Un-mark cells" })).toBeNull();
  });
});

describe("resolving unconfirmed cells", () => {
  const waiting = () => sheetRead(CODE, { used: [1], unconfirmed: [5, 6] });

  it.each([
    ["Printed, cell 5", "printed"],
    ["Not printed, cell 5", "not_printed"],
  ])("%s sends the outcome %s for that cell only", async (name, outcome) => {
    const { calls } = await open(waiting(), { [`POST ${PATH}/cells/resolve`]: sheetRead(CODE, { used: [1, 5], unconfirmed: [6] }) });
    await userEvent.click(screen.getByRole("button", { name }));
    await waitFor(() => expect(posts(calls)).toHaveLength(1));
    expect(body(posts(calls)[0]!)).toEqual({ cells: [5], outcome });
    await waitFor(() => expect(screen.queryByRole("button", { name: "Printed, cell 5" })).toBeNull());
    expect(screen.getByRole("button", { name: "Printed, cell 6" })).toBeVisible();
  });

  it("shows a refusal as words", async () => {
    await open(waiting(), {
      [`POST ${PATH}/cells/resolve`]: () => respond(409, apiErrorBody("cells_not_unconfirmed", "Some cells are not waiting for confirmation.", { cells: [5] })),
    });
    await userEvent.click(screen.getByRole("button", { name: "Printed, cell 5" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Those cells are no longer waiting for confirmation.");
  });

  it("shows a network error as words", async () => {
    await open(waiting(), {
      [`POST ${PATH}/cells/resolve`]: () => {
        throw new TypeError("Failed to fetch");
      },
    });
    await userEvent.click(screen.getByRole("button", { name: "Not printed, cell 6" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The server cannot be reached.");
  });
});

describe("resolving all unconfirmed cells at once (#282)", () => {
  const three = () => sheetRead(CODE, { used: [1], unconfirmed: [5, 6, 7] });
  const ALL = `${PATH}/cells/resolve-all`;

  it("shows the resolve-all buttons from two unconfirmed cells", async () => {
    await open(sheetRead(CODE, { used: [1], unconfirmed: [5, 6] }));
    expect(screen.getByRole("button", { name: "Resolve all as printed" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Resolve all as not printed" })).toBeVisible();
  });

  it("hides them with one unconfirmed cell", async () => {
    await open(sheetRead(CODE, { used: [1], unconfirmed: [5] }));
    expect(screen.getByRole("button", { name: "Printed, cell 5" })).toBeVisible();
    expect(screen.queryByRole("button", { name: /Resolve all/ })).toBeNull();
  });

  it("hides them for a read key", async () => {
    await open(three(), {}, READ_SESSION);
    expect(screen.queryByRole("button", { name: /Resolve all/ })).toBeNull();
  });

  it.each([
    ["Resolve all as printed", "Resolve 3 cells as printed?"],
    ["Resolve all as not printed", "Resolve 3 cells as not printed?"],
  ])("%s: the confirmation names the count (%s) and sends nothing yet", async (button, question) => {
    const { calls } = await open(three());
    await userEvent.click(screen.getByRole("button", { name: button }));
    const dialog = await screen.findByRole("alertdialog", { name: question });
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toBeVisible();
    expect(posts(calls)).toHaveLength(0);
  });

  it.each([
    ["Resolve all as printed", "printed"],
    ["Resolve all as not printed", "not_printed"],
  ])("%s: confirming sends the outcome %s and expected_count 3", async (button, outcome) => {
    const { calls } = await open(three(), { [`POST ${ALL}`]: sheetRead(CODE, { used: [1, 5, 6, 7] }) });
    await userEvent.click(screen.getByRole("button", { name: button }));
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(within(dialog).getByRole("button", { name: outcome === "printed" ? "Resolve as printed" : "Resolve as not printed" }));
    await waitFor(() => expect(posts(calls)).toHaveLength(1));
    expect(body(posts(calls)[0]!)).toEqual({ outcome, expected_count: 3 });
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(screen.queryByRole("heading", { name: "Unconfirmed cells" })).toBeNull();
  });

  it("Cancel sends nothing", async () => {
    const { calls } = await open(three());
    await userEvent.click(screen.getByRole("button", { name: "Resolve all as printed" }));
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(posts(calls)).toHaveLength(0);
  });

  it("a count change reloads the sheet and says so", async () => {
    const { calls } = await open(three(), {
      [`POST ${ALL}`]: () => respond(409, apiErrorBody("unconfirmed_count_changed", "The count changed.", { unconfirmed: 4 })),
    });
    const reads = () => calls.filter((c) => c.method === "GET" && c.path === PATH).length;
    const before = reads();
    await userEvent.click(screen.getByRole("button", { name: "Resolve all as printed" }));
    await userEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Resolve as printed" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The number of unconfirmed cells changed. Check the list and try again.");
    await waitFor(() => expect(reads()).toBeGreaterThan(before));
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("a network error is said in words, outside the closed dialog", async () => {
    await open(three(), {
      [`POST ${ALL}`]: () => {
        throw new TypeError("Failed to fetch");
      },
    });
    await userEvent.click(screen.getByRole("button", { name: "Resolve all as printed" }));
    await userEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Resolve as printed" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The server cannot be reached.");
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
  });

  it("while the request is out Cancel, Escape and the confirm button do nothing; the title keeps its count and never says 0", async () => {
    let release: (r: Response) => void = () => undefined;
    const { calls } = await open(three(), {
      [`POST ${ALL}`]: () => new Promise<Response>((resolve) => (release = resolve)),
    });
    const seen: string[] = [];
    const watcher = new MutationObserver(() => seen.push(document.body.textContent ?? ""));
    watcher.observe(document.body, { childList: true, subtree: true, characterData: true });
    await userEvent.click(screen.getByRole("button", { name: "Resolve all as printed" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Resolve 3 cells as printed?" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Resolve as printed" }));
    await waitFor(() => expect(posts(calls)).toHaveLength(1));
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toBeDisabled();
    expect(within(dialog).getByRole("button", { name: "Resolve as printed" })).toBeDisabled();
    await userEvent.keyboard("{Escape}");
    expect(screen.getByRole("alertdialog", { name: "Resolve 3 cells as printed?" })).toBeVisible();
    release(new Response(JSON.stringify(sheetRead(CODE, { used: [1, 5, 6, 7] })), { status: 200, headers: { "Content-Type": "application/json" } }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    watcher.disconnect();
    expect(seen.some((text) => /Resolve 0 cell/.test(text))).toBe(false);
    expect(posts(calls)).toHaveLength(1);
  });

  it("moves the focus to the sheet heading after the cells are settled", async () => {
    await open(three(), { [`POST ${ALL}`]: sheetRead(CODE, { used: [1, 5, 6, 7] }) });
    await userEvent.click(screen.getByRole("button", { name: "Resolve all as printed" }));
    await userEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Resolve as printed" }));
    await waitFor(() => expect(screen.getByRole("heading", { level: 1, name: CODE })).toHaveFocus());
  });

  it("a count-change message goes away with the next successful write", async () => {
    await open(three(), {
      [`POST ${ALL}`]: () => respond(409, apiErrorBody("unconfirmed_count_changed", "The count changed.", { unconfirmed: 4 })),
      [`POST ${PATH}/cells/resolve`]: sheetRead(CODE, { used: [1, 5], unconfirmed: [6, 7] }),
    });
    await userEvent.click(screen.getByRole("button", { name: "Resolve all as printed" }));
    await userEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Resolve as printed" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The number of unconfirmed cells changed.");
    await userEvent.click(screen.getByRole("button", { name: "Printed, cell 5" }));
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
  });

  it("nothing left to resolve is said in words", async () => {
    await open(three(), { [`POST ${ALL}`]: () => respond(409, apiErrorBody("no_unconfirmed_cells", "None.")) });
    await userEvent.click(screen.getByRole("button", { name: "Resolve all as not printed" }));
    await userEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Resolve as not printed" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("No cell is waiting for confirmation any more.");
  });
});

describe("discarding from the detail page", () => {
  it("asks first, then discards and shows the discarded state", async () => {
    const gone = sheetRead(CODE, { used: [1] }, { state: "discarded", discarded_at: "2026-11-02T12:00:00Z" });
    const { calls } = await open(sheetRead(CODE, { used: [1] }), { [`POST ${PATH}/discard`]: gone });
    await userEvent.click(screen.getByRole("button", { name: "Discard sheet" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText(/its number is never given out again/)).toBeVisible();
    expect(posts(calls)).toHaveLength(0);
    await userEvent.click(within(dialog).getByRole("button", { name: "Discard sheet" }));
    expect(await screen.findByText("Discarded on Nov 2, 2026, this ID is not used again.")).toBeVisible();
  });

  it("with unconfirmed cells the question says to resolve them first", async () => {
    await open(sheetRead(CODE, { used: [1], unconfirmed: [5] }));
    await userEvent.click(screen.getByRole("button", { name: "Discard sheet" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText(/Resolve the 1 unconfirmed cell first/)).toBeVisible();
  });

  it("shows sheet_busy as words", async () => {
    await open(sheetRead(CODE, { used: [1] }), {
      [`POST ${PATH}/discard`]: () => respond(409, apiErrorBody("sheet_busy", "Sheet is in use by a running job.")),
    });
    await userEvent.click(screen.getByRole("button", { name: "Discard sheet" }));
    await userEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Discard sheet" }));
    expect(await within(screen.getByRole("alertdialog")).findByText("A running job still uses this sheet. Try again when it has finished.")).toBeVisible();
  });

  it("shows a network error as words", async () => {
    await open(sheetRead(CODE, { used: [1] }), {
      [`POST ${PATH}/discard`]: () => {
        throw new TypeError("Failed to fetch");
      },
    });
    await userEvent.click(screen.getByRole("button", { name: "Discard sheet" }));
    await userEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Discard sheet" }));
    expect(await within(screen.getByRole("alertdialog")).findByText("The server cannot be reached.")).toBeVisible();
  });

  it("offers no Discard while a running job holds cells, and says why", async () => {
    await open(sheetRead(CODE, { used: [1], reserved: [2] }));
    expect(screen.queryByRole("button", { name: "Discard sheet" })).toBeNull();
    expect(screen.getByText("In use by a running job")).toBeVisible();
  });
});

describe("a sheet that changes while a choice is open (break-ui)", () => {
  it("drops a chosen cell that a job reserved meanwhile, instead of sending it", async () => {
    let sheet = sheetRead(CODE, { used: [1] });
    const { queryClient, calls } = await open(sheet, { [`GET ${PATH}`]: () => sheet, [`POST ${PATH}/cells/mark`]: sheetRead(CODE, { used: [1, 21] }) });
    await userEvent.click(screen.getByRole("button", { name: "Mark cells as used" }));
    await userEvent.click(cell(20));
    await userEvent.click(cell(21));
    expect(screen.getByRole("button", { name: "Mark 2 cells as used" })).toBeVisible();
    sheet = sheetRead(CODE, { used: [1], reserved: [20] });
    await act(async () => {
      await queryClient.invalidateQueries({ queryKey: sheetKey(CODE) });
    });
    await userEvent.click(await screen.findByRole("button", { name: "Mark 1 cell as used" }));
    await waitFor(() => expect(posts(calls)).toHaveLength(1));
    expect(body(posts(calls)[0]!)).toEqual({ cells: [{ cell: 21 }] });
  });

  it("closes an open choice when the sheet is discarded meanwhile", async () => {
    let sheet = sheetRead(CODE, { used: [1] });
    const { queryClient } = await open(sheet, { [`GET ${PATH}`]: () => sheet });
    await userEvent.click(screen.getByRole("button", { name: "Mark cells as used" }));
    expect(screen.getByRole("heading", { level: 2, name: "Mark cells as used" })).toBeVisible();
    sheet = sheetRead(CODE, { used: [1] }, { state: "discarded", discarded_at: "2026-11-02T12:00:00Z" });
    await act(async () => {
      await queryClient.invalidateQueries({ queryKey: sheetKey(CODE) });
    });
    expect(await screen.findByText("Discarded on Nov 2, 2026, this ID is not used again.")).toBeVisible();
    expect(screen.queryByRole("heading", { level: 2, name: "Mark cells as used" })).toBeNull();
  });
});

describe("a long list of cells", () => {
  it("starts folded above 30 cells and open below", async () => {
    const many = Array.from({ length: 40 }, (_, i) => i + 1);
    const { unmount } = await open(sheetRead(CODE, { used: many }));
    expect(screen.getByText("Show all 40 cells").closest("details")).not.toHaveAttribute("open");
    unmount();
    await open(sheetRead(CODE, { used: [1, 2, 3] }));
    expect(screen.getByRole("list", { name: "Cells in use" })).toBeVisible();
  });
});
