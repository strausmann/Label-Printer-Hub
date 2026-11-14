// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SIGNED_IN, renderApp } from "../../test-utils";
import { mockApi, PAGE_PRINTER, PRINTER_A, pageStatus, respond, status } from "../test-api";

afterEach(() => vi.unstubAllGlobals());

const JOB = "cccccccc-0000-4000-8000-000000000001";

function routes(printer: Record<string, unknown> & { id: string }, st: unknown, extra: Record<string, unknown> = {}) {
  return {
    [`GET /api/v1/printers/${printer.id}`]: printer,
    [`GET /api/v1/printers/${printer.id}/status`]: st,
    [`GET /api/v1/printers/${printer.id}/queue`]: [],
    [`POST /api/v1/printers/${printer.id}/test-print`]: respond(202, { job_id: JOB }),
    ...extra,
  };
}
const open = (printer: { id: string }, session = SIGNED_IN, language: "en" | "de" = "en") =>
  renderApp({ path: `/printers/${printer.id}`, session, language });
const posts = (calls: { method: string; path: string; body?: string }[]) => calls.filter((c) => c.method === "POST" && c.path.endsWith("/test-print"));

describe("TestPrintButton", () => {
  it("posts once for a tape printer and links to the job", async () => {
    const { calls } = mockApi(routes(PRINTER_A, status(PRINTER_A.id)));
    await open(PRINTER_A);
    await userEvent.click(await screen.findByRole("button", { name: "Test print" }));
    expect(await screen.findByText(/Test print sent/)).toBeVisible();
    expect(posts(calls)).toHaveLength(1);
    expect(posts(calls)[0]!.body).toBeUndefined();
    expect(screen.getByRole("link", { name: "Open the job" })).toHaveAttribute("href", `/jobs/${JOB}`);
  });

  it("is enabled for an unpolled tape printer", async () => {
    mockApi(routes(PRINTER_A, status(PRINTER_A.id, { polled: false, online: null, captured_at: null })));
    await open(PRINTER_A);
    expect(await screen.findByRole("button", { name: "Test print" })).toBeEnabled();
  });

  it("shows an answer after a refusal, and no job link", async () => {
    mockApi(routes(PRINTER_A, status(PRINTER_A.id), { [`POST /api/v1/printers/${PRINTER_A.id}/test-print`]: respond(409, { detail: { type: "printer-offline", title: "Printer offline", status: 409, detail: "The printer did not answer" } }) }));
    await open(PRINTER_A);
    await userEvent.click(await screen.findByRole("button", { name: "Test print" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/not reachable/);
    expect(screen.queryByRole("link", { name: "Open the job" })).toBeNull();
  });

  it("is disabled with the reason as visible text when the printer is paused", async () => {
    mockApi(routes({ ...PRINTER_A, paused: true }, status(PRINTER_A.id)));
    await open(PRINTER_A);
    const button = await screen.findByRole("button", { name: "Test print" });
    expect(button).toBeDisabled();
    expect(screen.getByText("Printer is paused")).toBeVisible();
    expect(button).toHaveAccessibleDescription("Printer is paused");
  });

  it("is disabled when the printer is disabled", async () => {
    mockApi(routes({ ...PRINTER_A, enabled: false }, status(PRINTER_A.id)));
    await open(PRINTER_A);
    expect(await screen.findByRole("button", { name: "Test print" })).toBeDisabled();
    expect(screen.getByText("Printer is disabled")).toBeVisible();
  });

  it.each([
    ["offline", { online: false }, "Printer is not reachable"],
    ["stale", { stale: true }, "Printer is not reachable"],
    ["unpolled", { polled: false, online: null }, "Printer status unknown"],
  ] as const)("is disabled with a reason when a page printer is %s", async (_name, over, reason) => {
    mockApi(routes(PAGE_PRINTER, pageStatus(PAGE_PRINTER.id, over)));
    await open(PAGE_PRINTER);
    expect(await screen.findByText(reason)).toBeVisible();
    expect(screen.getByRole("button", { name: "Test print" })).toBeDisabled();
  });

  it("test print disabled when printer stopped: the IPP state reason stands beside the button", async () => {
    mockApi(
      routes(
        PAGE_PRINTER,
        pageStatus(PAGE_PRINTER.id, {
          printer_state: "stopped",
          state_reasons: [{ keyword: "toner-empty", severity: "error", blocking: true }],
        }),
      ),
    );
    await open(PAGE_PRINTER);
    expect(await screen.findByText("Printer is stopped: toner empty")).toBeVisible();
    const button = screen.getByRole("button", { name: "Test print" });
    expect(button).toBeDisabled();
    expect(button).toHaveAccessibleDescription("Printer is stopped: toner empty");
  });

  it("a stopped printer that names no reason is still refused, without a dangling colon", async () => {
    mockApi(routes(PAGE_PRINTER, pageStatus(PAGE_PRINTER.id, { printer_state: "stopped", state_reasons: [] })));
    await open(PAGE_PRINTER);
    expect(await screen.findByText("Printer is stopped")).toBeVisible();
    expect(screen.getByRole("button", { name: "Test print" })).toBeDisabled();
  });

  it("is disabled as 'status unknown' while a page printer's status is still loading", async () => {
    // The status never answers: the button must not offer a print it cannot vouch for.
    mockApi(routes(PAGE_PRINTER, new Promise(() => undefined)));
    await open(PAGE_PRINTER);
    expect(await screen.findByText("Printer status unknown")).toBeVisible();
    expect(screen.getByRole("button", { name: "Test print" })).toBeDisabled();
  });

  it("is absent for a read-only key", async () => {
    mockApi(routes(PRINTER_A, status(PRINTER_A.id)));
    await open(PRINTER_A, { ...SIGNED_IN, scope: "read" });
    await screen.findByRole("heading", { name: PRINTER_A.name });
    expect(screen.queryByRole("button", { name: /Test print/ })).toBeNull();
  });

  it("is available to a print key", async () => {
    mockApi(routes(PRINTER_A, status(PRINTER_A.id)));
    await open(PRINTER_A, { ...SIGNED_IN, scope: "print" });
    expect(await screen.findByRole("button", { name: "Test print" })).toBeEnabled();
  });

  it("sends the chosen tray for a page printer", async () => {
    const { calls } = mockApi(routes(PAGE_PRINTER, pageStatus(PAGE_PRINTER.id)));
    await open(PAGE_PRINTER);
    await userEvent.click(await screen.findByRole("button", { name: "Test print" }));
    const dialog = await screen.findByRole("dialog");
    // The default tray is preselected.
    expect(within(dialog).getByRole("button", { name: /Tray/ })).toHaveTextContent("Main tray");
    await userEvent.click(within(dialog).getByRole("button", { name: /Tray/ }));
    await userEvent.click(await screen.findByRole("option", { name: "Bypass" }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Print test page" }));
    await waitFor(() => expect(posts(calls)).toHaveLength(1));
    expect(JSON.parse(posts(calls)[0]!.body!)).toEqual({ tray: "bypass" });
    expect(await screen.findByRole("link", { name: "Open the job" })).toBeVisible();
  });

  it("reads in German with the glossary terms", async () => {
    mockApi(routes({ ...PRINTER_A, paused: true }, status(PRINTER_A.id)));
    await open(PRINTER_A, SIGNED_IN, "de");
    expect(await screen.findByRole("button", { name: "Testdruck" })).toBeDisabled();
    expect(screen.getByText("Der Drucker ist pausiert")).toBeVisible();
  });

  it.each([
    ["printer-offline", "The printer is not reachable. Check that it is switched on and connected, then try again."],
    ["no-tape-loaded", "No tape is loaded. Put in a tape and try again."],
    ["media-unknown", "The printer does not report which paper is in the tray. Set the paper size on the printer or choose another tray."],
    ["printer-disabled", "The printer is switched off in the hub. Switch it on in the printer settings."],
    ["printer-paused", "The printer is paused. Resume it, then try again."],
    ["printer-status-unknown", "The hub cannot read this printer's status, so it cannot tell whether it is ready. An admin can check its address in the printer settings, then try again."],
  ])("explains %s in the app's own words, not the server's English", async (type, words) => {
    const route = { [`POST /api/v1/printers/${PRINTER_A.id}/test-print`]: respond(409, { detail: { type, title: "T", status: 409, detail: "server text" } }) };
    mockApi(routes(PRINTER_A, status(PRINTER_A.id), route));
    await open(PRINTER_A);
    await userEvent.click(await screen.findByRole("button", { name: "Test print" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(words);
  });

  it.each([
    ["printer-paused", "Der Drucker ist pausiert. Setze ihn fort und versuche es dann erneut."],
    ["printer-status-unknown", "Der Hub kann den Status dieses Druckers nicht lesen und weiß deshalb nicht, ob er bereit ist. Ein Admin kann seine Adresse in den Druckereinstellungen prüfen. Versuche es dann erneut."],
  ])("refusal texts are localized: %s reads German in a German UI", async (type, words) => {
    const route = { [`POST /api/v1/printers/${PRINTER_A.id}/test-print`]: respond(409, { detail: { type, title: "T", status: 409, detail: "server text" } }) };
    mockApi(routes(PRINTER_A, status(PRINTER_A.id), route));
    await open(PRINTER_A, SIGNED_IN, "de");
    await userEvent.click(await screen.findByRole("button", { name: "Testdruck" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(words);
    expect(alert).not.toHaveTextContent("server text");
  });

  it("says the same in German", async () => {
    const route = { [`POST /api/v1/printers/${PRINTER_A.id}/test-print`]: respond(409, { detail: { type: "no-tape-loaded", title: "T", status: 409, detail: "server text" } }) };
    mockApi(routes(PRINTER_A, status(PRINTER_A.id), route));
    await open(PRINTER_A, SIGNED_IN, "de");
    await userEvent.click(await screen.findByRole("button", { name: "Testdruck" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Es ist kein Band eingelegt. Lege ein Band ein und versuche es noch einmal.");
  });

  it("keeps the API detail for a problem type it does not know", async () => {
    const route = { [`POST /api/v1/printers/${PRINTER_A.id}/test-print`]: respond(409, { detail: { type: "something-new", title: "T", status: 409, detail: "The hub says this." } }) };
    mockApi(routes(PRINTER_A, status(PRINTER_A.id), route));
    await open(PRINTER_A);
    await userEvent.click(await screen.findByRole("button", { name: "Test print" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The hub says this.");
  });
});
