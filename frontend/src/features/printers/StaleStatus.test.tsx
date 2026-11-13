import { screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderApp, SIGNED_IN } from "../../test-utils";
import { mockApi, PAGE_PRINTER, pageStatus, PRINTER_A, status } from "../test-api";

afterEach(() => vi.unstubAllGlobals());

const routes = (over: Record<string, unknown>) => ({
  "GET /api/v1/printers": [PRINTER_A],
  [`GET /api/v1/printers/${PRINTER_A.id}/status`]: status(PRINTER_A.id, over),
  "GET /api/v1/jobs": [],
});

describe("a status nobody refreshes (#227)", () => {
  it("a stale tape printer says Status unknown with its age, never Ready or a tape", async () => {
    mockApi(
      routes({ online: null, stale: true, tape_loaded: null, last_probe_age_s: 12349795, note: "Status older than 90 s" }),
    );
    await renderApp({ path: "/printers" });
    const card = (await screen.findByRole("link", { name: /Workshop PT-P750W/ })) as HTMLElement;
    expect(await within(card).findByText("Status unknown")).toBeVisible();
    expect(within(card).getByText("Last status 142 days ago")).toBeVisible();
    expect(within(card).getByText("Tape not known")).toBeVisible();
    expect(within(card).queryByText("Ready")).toBeNull();
    expect(within(card).queryByText("No tape loaded")).toBeNull();
  });

  it("an unpolled printer says Not monitored", async () => {
    mockApi(routes({ online: null, polled: false, tape_loaded: null, note: "Not polled" }));
    await renderApp({ path: "/printers" });
    const card = (await screen.findByRole("link", { name: /Workshop PT-P750W/ })) as HTMLElement;
    expect(await within(card).findByText("Not monitored")).toBeVisible();
    expect(within(card).queryByText("Ready")).toBeNull();
  });
});

const detailRoutes = (over: Record<string, unknown>) => ({
  [`GET /api/v1/printers/${PRINTER_A.id}`]: PRINTER_A,
  [`GET /api/v1/printers/${PRINTER_A.id}/status`]: status(PRINTER_A.id, over),
  [`GET /api/v1/printers/${PRINTER_A.id}/queue`]: [],
});

describe("one age rule for the card and the detail page (263-28)", () => {
  const cases = [
    ["a fresh status", { last_probe_age_s: 4 }, null],
    ["a stale status", { online: null, stale: true, tape_loaded: null, last_probe_age_s: 12349795 }, "Last status 142 days ago"],
    ["an unpolled status that has an age", { online: null, polled: false, tape_loaded: null, last_probe_age_s: 7300 }, "Last status 2 hours ago"],
  ] as const;

  it.each(cases)("same age rule on card and detail: %s", async (_name, over, line) => {
    mockApi({ "GET /api/v1/printers": [PRINTER_A], ...detailRoutes(over), "GET /api/v1/jobs": [] });
    const list = await renderApp({ path: "/printers" });
    const card = (await screen.findByRole("link", { name: /Workshop PT-P750W/ })) as HTMLElement;
    await within(card).findByText(/Ready|Status unknown|Not monitored/);
    if (line) expect(within(card).getByText(line)).toBeVisible();
    else expect(within(card).queryByText(/Last status/)).toBeNull();
    list.unmount();

    await renderApp({ path: `/printers/${PRINTER_A.id}` });
    // The status has arrived once the headline names a state; before that "no line" would hold for any rule.
    const header = (await screen.findByRole("heading", { level: 1, name: PRINTER_A.name })).closest("header")!;
    await within(header).findByText(/^(Ready|Status unknown|Not monitored)$/);
    if (line) expect(await screen.findByText(line)).toBeVisible();
    else expect(screen.queryByText(/Last status/)).toBeNull();
  });

  // #296: the printer form has no switch for status discovery yet, so the hint must not send anyone there.
  const TAPE_HINT = "Status discovery is off for this printer. An admin can turn it on through the admin API.";
  const HOW_TO = "How to turn on status discovery";
  const DOCS = "https://github.com/strausmann/label-printer-hub/blob/main/docs/getting-started.md#turn-on-status-discovery";

  it("not monitored names what is true today: text on the card, the admin API how-to for an admin on the detail page", async () => {
    mockApi({ "GET /api/v1/printers": [PRINTER_A], ...detailRoutes({ online: null, polled: false, tape_loaded: null, note: "Not polled" }), "GET /api/v1/jobs": [] });
    const list = await renderApp({ path: "/printers" });
    const card = (await screen.findByRole("link", { name: /Workshop PT-P750W/ })) as HTMLElement;
    expect(await within(card).findByText(TAPE_HINT)).toBeVisible();
    // The card is itself a link: no second link inside it.
    expect(within(card).queryByRole("link")).toBeNull();
    list.unmount();

    const detail = await renderApp({ path: `/printers/${PRINTER_A.id}` });
    expect(await screen.findByText(TAPE_HINT)).toBeVisible();
    expect(screen.getByRole("link", { name: HOW_TO })).toHaveAttribute("href", DOCS);
    expect(screen.queryByRole("link", { name: "Open the printer settings" })).toBeNull();
    expect(screen.queryByText(/in the printer settings/)).toBeNull();
    detail.unmount();

    // A key below admin cannot use the admin API: the hint stays, the link goes.
    await renderApp({ path: `/printers/${PRINTER_A.id}`, session: { ...SIGNED_IN, scope: "print" } });
    expect(await screen.findByText(TAPE_HINT)).toBeVisible();
    expect(screen.queryByRole("link", { name: HOW_TO })).toBeNull();
  });

  it("the how-to link points at the docs of the running version", async () => {
    mockApi({ "GET /api/v1/printers": [PRINTER_A], ...detailRoutes({ online: null, polled: false, tape_loaded: null }), "GET /api/v1/jobs": [] });
    await renderApp({ path: `/printers/${PRINTER_A.id}`, info: { source_url: "https://example.invalid/fork/tree/v1.5.1" } });
    expect(await screen.findByRole("link", { name: HOW_TO })).toHaveAttribute(
      "href",
      "https://example.invalid/fork/blob/v1.5.1/docs/getting-started.md#turn-on-status-discovery",
    );
  });

  it("an unpolled page printer is not about status discovery: an admin checks its address", async () => {
    const page = { ...PAGE_PRINTER };
    mockApi({
      "GET /api/v1/printers": [page],
      [`GET /api/v1/printers/${page.id}`]: page,
      [`GET /api/v1/printers/${page.id}/status`]: pageStatus(page.id, { online: null, polled: false, markers: [], trays: [] }),
      [`GET /api/v1/printers/${page.id}/queue`]: [],
      "GET /api/v1/jobs": [],
    });
    const list = await renderApp({ path: "/printers" });
    const card = (await screen.findByRole("link", { name: /Office laser/ })) as HTMLElement;
    expect(await within(card).findByText("The hub cannot read this printer's status. An admin can check its address in the printer settings.")).toBeVisible();
    expect(within(card).queryByText(/status discovery/)).toBeNull();
    list.unmount();

    await renderApp({ path: `/printers/${page.id}` });
    expect(await screen.findByRole("link", { name: "Open the printer settings" })).toHaveAttribute("href", "/settings/printers");
  });

  it("a printer switched off in the hub says so, not that discovery is off", async () => {
    const off = { ...PRINTER_A, enabled: false };
    mockApi({ "GET /api/v1/printers": [off], ...detailRoutes({ online: null, polled: false, tape_loaded: null }), [`GET /api/v1/printers/${PRINTER_A.id}`]: off, "GET /api/v1/jobs": [] });
    await renderApp({ path: "/printers" });
    const card = (await screen.findByRole("link", { name: /Workshop PT-P750W/ })) as HTMLElement;
    expect(await within(card).findByText("The printer is switched off in the hub. Switch it on in the printer settings.")).toBeVisible();
    expect(within(card).queryByText(/status discovery/)).toBeNull();
  });

  it("a monitored printer gets no such hint", async () => {
    mockApi({ "GET /api/v1/printers": [PRINTER_A], ...detailRoutes({}), "GET /api/v1/jobs": [] });
    await renderApp({ path: "/printers" });
    const card = (await screen.findByRole("link", { name: /Workshop PT-P750W/ })) as HTMLElement;
    await within(card).findByText("Ready");
    expect(screen.queryByText(/status discovery/)).toBeNull();
  });
});
