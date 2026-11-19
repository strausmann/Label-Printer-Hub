// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { QueryClient } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { renderApp, SIGNED_IN } from "../../test-utils";
import { apiErrorBody, mockApi, pageStatus, respond } from "../test-api";
import { statusKey } from "../printers/api";
import { enter, only, P, resetBetweenTests, routes } from "./CalibrationPage.kit";

vi.setConfig({ testTimeout: 15_000 });
resetBetweenTests();

const STATUS = `GET /api/v1/printers/${P}/status`;
const hourAgo = () => new Date(Date.now() - 3_600_000).toISOString();

/** Opens the page; the status answers as given, `seed` fills the cache first. */
async function openWith(
  status: unknown,
  { path = `/calibration?printer=${P}`, seed }: { path?: string; seed?: (client: QueryClient) => void } = {},
) {
  const api = mockApi(routes({ [STATUS]: status }));
  const app = await renderApp({ path, session: SIGNED_IN, seed });
  return { ...api, ...app };
}
const tray = (app: { router: { state: { location: { search: unknown } } } }) => (app.router.state.location.search as { tray?: string }).tray;
const trayButton = () => screen.findByRole("button", { name: /Tray$/ });

describe("the tray the page starts on (#344)", () => {
  it("preselects the tray last used for sheets", async () => {
    const app = await openWith(pageStatus(P, { last_sheet_tray: "bypass" }));
    expect(await trayButton()).toHaveTextContent("Bypass");
    await waitFor(() => expect(tray(app)).toBe("bypass"));
  });

  it("falls back to the default tray", async () => {
    const app = await openWith(pageStatus(P));
    expect(await trayButton()).toHaveTextContent("Main tray");
    await waitFor(() => expect(tray(app)).toBe("main"));
  });

  it("waits for the status before choosing the tray", async () => {
    let release: (v: unknown) => void = () => undefined;
    const pending = new Promise((resolve) => (release = resolve));
    const app = await openWith(() => pending as Promise<unknown>);
    await screen.findByRole("heading", { level: 1, name: "Calibration" });
    // The calibration and the capabilities are in by now; only the status is missing.
    await waitFor(() => expect(screen.getAllByRole("status").some((x) => x.textContent === "Loading…")).toBe(true));
    await new Promise((r) => setTimeout(r, 100));
    expect(screen.queryByRole("button", { name: "Print the calibration page (without correction)" })).toBeNull();
    expect(tray(app)).toBeUndefined();
    await act(async () => release(pageStatus(P, { last_sheet_tray: "bypass" })));
    expect(await screen.findByRole("button", { name: "Print the calibration page (without correction)" })).toBeVisible();
    await waitFor(() => expect(tray(app)).toBe("bypass"));
  });

  it("a cached status does not decide, the refetch does", async () => {
    const seen = new Set<string | undefined>();
    const app = await openWith(pageStatus(P, { last_sheet_tray: "bypass" }), {
      seed: (client) => client.setQueryData(statusKey(P), pageStatus(P, { last_sheet_tray: "main" })),
    });
    app.router.subscribe("onResolved", () => seen.add(tray(app)));
    await waitFor(() => expect(tray(app)).toBe("bypass"));
    expect(seen.has("main")).toBe(false);
    expect(await trayButton()).toHaveTextContent("Bypass");
  });

  it("a status fetched a moment ago is refetched before the tray is chosen", async () => {
    const { calls } = await openWith(pageStatus(P, { last_sheet_tray: "bypass" }), {
      seed: (client) => client.setQueryData(statusKey(P), pageStatus(P, { last_sheet_tray: "bypass" }), { updatedAt: Date.now() - 1000 }),
    });
    expect(await trayButton()).toHaveTextContent("Bypass");
    expect(only(calls, "GET", "/status").filter((c) => c.path.includes(P))).toHaveLength(1);
  });

  it("a failed status fetch falls back to the default tray", async () => {
    const app = await openWith(() => respond(503, apiErrorBody("unavailable", "Down.")), {
      seed: (client) => client.setQueryData(statusKey(P), pageStatus(P, { last_sheet_tray: "bypass" }), { updatedAt: Date.now() - 60_000 }),
    });
    // The status is not retried: the page gives up on it at once.
    await waitFor(() => expect(tray(app)).toBe("main"), { timeout: 4000 });
    expect(await trayButton()).toHaveTextContent("Main tray");
  });

  it("a status refetch after the print keeps the form", async () => {
    const { calls, queryClient } = await openWith(pageStatus(P, { last_sheet_tray: "bypass" }));
    await screen.findByRole("button", { name: "Print the calibration page (without correction)" });
    await enter("Offset X (mm)", "0,9");
    const before = only(calls, "GET", "/status").length;
    await act(async () => void queryClient.invalidateQueries({ queryKey: statusKey(P) }));
    await waitFor(() => expect(only(calls, "GET", "/status").length).toBeGreaterThan(before));
    expect(screen.getByLabelText("Offset X (mm)")).toHaveValue("0,9");
    expect(screen.queryByRole("status", { name: "Calibration page status" })).not.toBeNull();
  });
});

describe("the trays named by each step (#344)", () => {
  const open = (over: Parameters<typeof pageStatus>[1] = {}, tray = "main") =>
    openWith(pageStatus(P, over), { path: `/calibration?printer=${P}&tray=${tray}` });

  it("each step names its tray", async () => {
    await open({}, "bypass");
    expect(await screen.findByText("Prints from: Bypass")).toBeVisible();
    expect(screen.getByText("Saves for: Bypass")).toBeVisible();
  });

  it("warns when the calibration page was requested from another tray", async () => {
    await open({ last_calibration_print: { tray: "bypass", at: hourAgo() } });
    const warning = await screen.findByText(/The calibration page was printed from/);
    expect(warning).toHaveTextContent("Bypass");
    expect(warning).toHaveTextContent("Main tray");
    expect(screen.getByText("Check the tray:")).toBeVisible();
  });

  it("warns when sheets print from another tray", async () => {
    await open({ last_sheet_tray: "bypass" });
    const warning = await screen.findByText(/Sheets last printed from/);
    expect(warning).toHaveTextContent("Bypass");
    expect(screen.getByText("Check the tray:")).toBeVisible();
  });

  it("with both warnings the lead and each phrase appear once", async () => {
    await open({ last_sheet_tray: "bypass", last_calibration_print: { tray: "bypass", at: hourAgo() } });
    await screen.findByText(/Sheets last printed from/);
    expect(screen.getAllByText("Check the tray:")).toHaveLength(1);
    expect(screen.getAllByText(/The calibration page was printed from/)).toHaveLength(1);
    expect(screen.getAllByText(/^Prints from:/)).toHaveLength(1);
  });

  it("no warning when the trays agree", async () => {
    await open({ last_sheet_tray: "main", last_calibration_print: { tray: "main", at: hourAgo() } });
    await screen.findByText("Saves for: Main tray");
    expect(screen.queryByText("Check the tray:")).toBeNull();
  });

  it("saving stays possible with a warning", async () => {
    const { calls } = await openWith(pageStatus(P, { last_sheet_tray: "bypass" }), {
      path: `/calibration?printer=${P}&tray=main`,
    });
    await screen.findByText(/Sheets last printed from/);
    await userEvent.click(screen.getByRole("button", { name: "Save for this printer and tray" }));
    await waitFor(() => expect(only(calls, "PUT")).toHaveLength(1));
  });
});
