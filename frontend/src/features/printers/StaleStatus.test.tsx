import { screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderApp, SIGNED_IN } from "../../test-utils";
import { mockApi, PRINTER_A, status } from "../test-api";

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

  it("not monitored names the fix: text on the card, text and a way to the settings for an admin on the detail page", async () => {
    mockApi({ "GET /api/v1/printers": [PRINTER_A], ...detailRoutes({ online: null, polled: false, tape_loaded: null, note: "Not polled" }), "GET /api/v1/jobs": [] });
    const list = await renderApp({ path: "/printers" });
    const card = (await screen.findByRole("link", { name: /Workshop PT-P750W/ })) as HTMLElement;
    expect(await within(card).findByText("Turn on status discovery in the printer settings")).toBeVisible();
    // The card is itself a link: no second link inside it.
    expect(within(card).queryByRole("link")).toBeNull();
    list.unmount();

    const detail = await renderApp({ path: `/printers/${PRINTER_A.id}` });
    expect(await screen.findByText("Turn on status discovery in the printer settings")).toBeVisible();
    expect(screen.getByRole("link", { name: "Open the printer settings" })).toHaveAttribute("href", "/settings/printers");
    detail.unmount();

    // A key below admin cannot change settings: the hint stays, the link goes.
    await renderApp({ path: `/printers/${PRINTER_A.id}`, session: { ...SIGNED_IN, scope: "print" } });
    expect(await screen.findByText("Turn on status discovery in the printer settings")).toBeVisible();
    expect(screen.queryByRole("link", { name: "Open the printer settings" })).toBeNull();
  });

  it("a monitored printer gets no such hint", async () => {
    mockApi({ "GET /api/v1/printers": [PRINTER_A], ...detailRoutes({}), "GET /api/v1/jobs": [] });
    await renderApp({ path: "/printers" });
    const card = (await screen.findByRole("link", { name: /Workshop PT-P750W/ })) as HTMLElement;
    await within(card).findByText("Ready");
    expect(screen.queryByText(/status discovery/)).toBeNull();
  });
});
