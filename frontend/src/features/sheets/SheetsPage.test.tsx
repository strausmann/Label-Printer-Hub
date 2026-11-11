import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderApp, SIGNED_IN } from "../../test-utils";
import { parseSheetsSearch } from "./search";
import { apiErrorBody, mockApi, respond, sheetRead, sheetSummary, SHEET_TYPE, type Call } from "../test-api";

const PRINT_SESSION = { ...SIGNED_IN, scope: "print" as const };
const READ_SESSION = { ...SIGNED_IN, scope: "read" as const };

const FRESH = sheetSummary("L4736-0001", { used: 17, free: 31 });
const FULL = sheetSummary("L4736-0002", { used: 48, free: 0 });
const GONE = sheetSummary("L4736-0003", { state: "discarded", used: 5, free: 43 });
const ALL = [FRESH, FULL, GONE];

// Whole-app renders with a dialog and a select: under coverage and a loaded runner they need more than 5 s.
vi.setConfig({ testTimeout: 10_000 });

afterEach(() => vi.unstubAllGlobals());

/**
 * The list the way the server answers it: `state=active` has no discarded sheets, `all` has every
 * one. It reads the request's own query, so a page that forgets to send the filter fails here.
 */
function sheetsRoute(rows: ReturnType<typeof sheetSummary>[], calls: () => Call[]) {
  return () => {
    const state = new URLSearchParams(calls().at(-1)!.search).get("state");
    return rows.filter((s) => (state === "all" ? true : state === "discarded" ? s.state === "discarded" : s.state === "active"));
  };
}

function setup(rows = ALL, extra: Record<string, unknown> = {}) {
  let calls: Call[] = [];
  const api = mockApi({
    "GET /api/v1/sheets": sheetsRoute(rows, () => calls),
    "GET /api/v1/sheet-types": [SHEET_TYPE],
    ...extra,
  });
  calls = api.calls;
  return api;
}

const sheetCalls = (calls: Call[]) => calls.filter((c) => c.method === "GET" && c.path === "/api/v1/sheets");
const rowOf = (code: string) => screen.getByRole("link", { name: code }).closest("[role=row]") as HTMLElement;

describe("the sheet list", () => {
  it("hides used-up sheets by default and shows them when asked, judged by the rows", async () => {
    const { calls } = setup();
    await renderApp({ path: "/sheets", session: PRINT_SESSION });
    await screen.findByRole("link", { name: "L4736-0001" });
    expect(screen.queryByRole("link", { name: "L4736-0002" })).toBeNull();
    // The server cannot filter "full" out of "active": the page does, so it sends no such parameter.
    const first = sheetCalls(calls)[0]!;
    expect(new URLSearchParams(first.search).get("state")).toBe("active");
    expect(new URLSearchParams(first.search).has("free_at_least")).toBe(false);

    await userEvent.click(screen.getByRole("switch", { name: "Hide used-up sheets" }));
    const full = await screen.findByRole("link", { name: "L4736-0002" });
    expect(within(full.closest("[role=row]") as HTMLElement).getByText("used up")).toBeVisible();
    expect(within(rowOf("L4736-0001")).queryByText("used up")).toBeNull();
  });

  it("says how many used-up sheets are hidden", async () => {
    setup();
    await renderApp({ path: "/sheets", session: PRINT_SESSION });
    expect(await screen.findByText("1 used-up sheet hidden")).toBeVisible();
  });

  it("keeps discarded sheets behind a filter and gives them no Discard button", async () => {
    const { calls } = setup();
    await renderApp({ path: "/sheets?full=true", session: PRINT_SESSION });
    await screen.findByRole("link", { name: "L4736-0002" });
    expect(screen.queryByRole("link", { name: "L4736-0003" })).toBeNull();

    await userEvent.click(screen.getByRole("switch", { name: "Show discarded sheets" }));
    const gone = await screen.findByRole("link", { name: "L4736-0003" });
    const row = gone.closest("[role=row]") as HTMLElement;
    expect(within(row).getByText("discarded")).toBeVisible();
    expect(within(row).queryByRole("button", { name: /Discard/ })).toBeNull();
    expect(sheetCalls(calls).some((c) => new URLSearchParams(c.search).get("state") === "all")).toBe(true);
  });

  it("shows the numbers as words next to the bar, with reserved and unconfirmed cells not counted as free", async () => {
    setup([sheetSummary("L4736-0001", { used: 10, reserved: 2, unconfirmed: 1, free: 35 })]);
    await renderApp({ path: "/sheets", session: PRINT_SESSION });
    const row = rowOf(await screen.findByRole("link", { name: "L4736-0001" }).then((l) => l.textContent!));
    expect(within(row).getByText("10 of 48 used")).toBeVisible();
    expect(within(row).getByText("35 free")).toBeVisible();
    expect(within(row).getByText("2 reserved")).toBeVisible();
    expect(within(row).getByText("1 unconfirmed")).toBeVisible();
  });

  it("names the type with the label size and the code in the mono face", async () => {
    setup();
    await renderApp({ path: "/sheets", session: PRINT_SESSION });
    const link = await screen.findByRole("link", { name: "L4736-0001" });
    expect(link).toHaveClass("font-mono");
    expect(link).toHaveAttribute("href", "/sheets/L4736-0001");
    expect(within(rowOf("L4736-0001")).getByText(/L4736REV · 45\.7 × 21\.2 mm/)).toBeVisible();
  });

  it("sends the type and the code search of the address to the server and keeps them in the address", async () => {
    const { calls } = setup();
    const { router } = await renderApp({ path: "/sheets?type=L4736REV&q=0001", session: PRINT_SESSION });
    await screen.findByRole("link", { name: "L4736-0001" });
    const params = new URLSearchParams(sheetCalls(calls)[0]!.search);
    expect(params.get("type")).toBe("L4736REV");
    expect(params.get("q")).toBe("0001");

    await userEvent.type(screen.getByRole("textbox", { name: "Search by code" }), "2");
    await waitFor(() => expect(router.state.location.search).toMatchObject({ q: "00012" }));
  });

  it("drops values in the address that make no sense", async () => {
    const { calls } = setup();
    const { router } = await renderApp({ path: "/sheets?type=&q=%20&full=nope&discarded=1", session: PRINT_SESSION });
    await screen.findByRole("link", { name: "L4736-0001" });
    expect(router.state.location.search).toEqual({ discarded: true });
    expect(new URLSearchParams(sheetCalls(calls)[0]!.search).get("state")).toBe("all");
  });

  it("says so when there are no sheets at all, and when a filter hides every one", async () => {
    setup([]);
    const first = await renderApp({ path: "/sheets", session: PRINT_SESSION });
    expect(await screen.findByText("No sheets yet.")).toBeVisible();
    expect(screen.getByRole("button", { name: "New sheet" })).toBeVisible();
    first.unmount();

    setup([]);
    await renderApp({ path: "/sheets?q=zzz", session: PRINT_SESSION });
    expect(await screen.findByText("No sheet matches.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Clear filters" })).toBeVisible();
  });

  it("says so when the list cannot be loaded", async () => {
    mockApi({ "GET /api/v1/sheets": () => respond(403, { detail: "no" }), "GET /api/v1/sheet-types": [SHEET_TYPE] });
    await renderApp({ path: "/sheets", session: PRINT_SESSION });
    expect(await screen.findByText("The sheets could not be loaded.")).toBeVisible();
  });

  it("copes with hundreds of sheets and very long type names", async () => {
    const many = Array.from({ length: 300 }, (_, i) =>
      sheetSummary(`L4736-${String(i + 1).padStart(4, "0")}`, { used: 1, free: 47, type_label: "A-very-long-type-name-".repeat(8) }),
    );
    setup(many);
    await renderApp({ path: "/sheets", session: PRINT_SESSION });
    await screen.findByRole("link", { name: "L4736-0300" });
    expect(screen.getAllByRole("row")).toHaveLength(301); // header row + 300
  });
});

describe("the code search", () => {
  it("takes at most as many characters as the server accepts and never asks for more", async () => {
    const { calls } = setup();
    const { router } = await renderApp({ path: "/sheets", session: PRINT_SESSION });
    const box = await screen.findByRole("textbox", { name: "Search by code" });
    expect(box).toHaveAttribute("maxlength", "24");
    await userEvent.type(box, "L4736-0001-and-a-long-tail-of-text");
    expect(box).toHaveValue("L4736-0001-and-a-long-ta");
    await waitFor(() => expect(router.state.location.search).toMatchObject({ q: "L4736-0001-and-a-long-ta" }));
    expect(sheetCalls(calls).every((c) => (new URLSearchParams(c.search).get("q") ?? "").length <= 24)).toBe(true);
  });

  it("clamps a longer code search arriving in the address", async () => {
    const { calls } = setup();
    await renderApp({ path: `/sheets?q=${"x".repeat(40)}`, session: PRINT_SESSION });
    await waitFor(() => expect(sheetCalls(calls).length).toBeGreaterThan(0));
    expect(sheetCalls(calls).every((c) => (new URLSearchParams(c.search).get("q") ?? "").length <= 24)).toBe(true);
  });
});

describe("the code search clamp", () => {
  // The router's own query parsing already trims what it hands over, so the pure function is tested directly.
  it("leaves no trailing space when the cut falls behind a space", () => {
    expect(parseSheetsSearch({ q: "L4736-0001-and-a-long-x tail" }).q).toBe("L4736-0001-and-a-long-x");
    expect(parseSheetsSearch({ q: "L4736-0001-and-a-long-x" }).q).toBe("L4736-0001-and-a-long-x");
  });
});

describe("types in the filter", () => {
  it("are named by label and key, like the rows", async () => {
    setup();
    await renderApp({ path: "/sheets", session: PRINT_SESSION });
    await userEvent.click(await screen.findByRole("button", { name: /Sheet type/ }));
    expect((await screen.findAllByRole("option")).map((o) => o.textContent)).toEqual(["Any sheet type", "Example Labels L4736REV-25 (L4736REV)"]);
  });
});

describe("the hidden-sheets hint", () => {
  it("has a Show them button that is a 44 px target (an inline box ignores min-height)", async () => {
    setup();
    await renderApp({ path: "/sheets", session: PRINT_SESSION });
    const button = await screen.findByRole("button", { name: "Show them" });
    expect(button).toHaveClass("inline-flex", "min-h-11");
    expect(button).not.toHaveClass("inline");
  });
});

describe("discarding a sheet", () => {
  it("asks first with the mockup's words and posts only after the answer", async () => {
    const { calls } = setup(ALL, {
      "POST /api/v1/sheets/L4736-0001/discard": sheetRead("L4736-0001", { used: [1] }, { state: "discarded" }),
    });
    await renderApp({ path: "/sheets", session: PRINT_SESSION });
    await userEvent.click(await screen.findByRole("button", { name: "Discard L4736-0001" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(
      within(dialog).getByText(
        "Discard L4736-0001? It leaves the picker; its number is never given out again; labels already printed stay printed.",
      ),
    ).toBeVisible();
    expect(calls.some((c) => c.method === "POST")).toBe(false);

    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(calls.some((c) => c.method === "POST")).toBe(false);

    await userEvent.click(screen.getByRole("button", { name: "Discard L4736-0001" }));
    await userEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Discard sheet" }));
    await waitFor(() => expect(calls.filter((c) => c.method === "POST").map((c) => c.path)).toEqual(["/api/v1/sheets/L4736-0001/discard"]));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
  });

  it("offers no Discard while cells are reserved by a running job, and says why", async () => {
    setup([sheetSummary("L4736-0001", { used: 4, reserved: 3, free: 41 })]);
    await renderApp({ path: "/sheets", session: PRINT_SESSION });
    const row = rowOf(await screen.findByRole("link", { name: "L4736-0001" }).then((l) => l.textContent!));
    expect(within(row).queryByRole("button", { name: /Discard/ })).toBeNull();
    expect(within(row).getByText("In use by a running job")).toBeVisible();
  });

  it("with unconfirmed cells the question says to resolve them first and links to them", async () => {
    setup([sheetSummary("L4736-0001", { used: 4, unconfirmed: 3, free: 41 })]);
    await renderApp({ path: "/sheets", session: PRINT_SESSION });
    await userEvent.click(await screen.findByRole("button", { name: "Discard L4736-0001" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText("Resolve the 3 unconfirmed cells first; once the sheet is discarded they can no longer be cleaned up.")).toBeVisible();
    expect(within(dialog).getByRole("link", { name: "Show the unconfirmed cells" })).toHaveAttribute("href", "/sheets/L4736-0001");
    // The action stays available for whoever insists.
    expect(within(dialog).getByRole("button", { name: "Discard sheet" })).toBeEnabled();
  });

  it("shows sheet_busy as words and keeps the question open", async () => {
    setup(ALL, {
      "POST /api/v1/sheets/L4736-0001/discard": () => respond(409, apiErrorBody("sheet_busy", "Sheet is in use by a running job.")),
    });
    await renderApp({ path: "/sheets", session: PRINT_SESSION });
    await userEvent.click(await screen.findByRole("button", { name: "Discard L4736-0001" }));
    await userEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Discard sheet" }));
    expect(await within(screen.getByRole("alertdialog")).findByText("A running job still uses this sheet. Try again when it has finished.")).toBeVisible();
  });

  it("hides the Discard buttons and the New sheet button from a read key", async () => {
    setup();
    await renderApp({ path: "/sheets", session: READ_SESSION });
    await screen.findByRole("link", { name: "L4736-0001" });
    expect(screen.queryByRole("button", { name: /Discard/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "New sheet" })).toBeNull();
  });
});
