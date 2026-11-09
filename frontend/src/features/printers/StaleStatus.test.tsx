import { screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderApp } from "../../test-utils";
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
