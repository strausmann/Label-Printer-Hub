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

  it("shows the API detail after a refusal, and nothing was queued", async () => {
    const detail = "The printer is offline. Check the power and the network, then try again.";
    mockApi(routes(PRINTER_A, status(PRINTER_A.id), { [`POST /api/v1/printers/${PRINTER_A.id}/test-print`]: respond(409, { detail: { type: "printer-offline", title: "Printer offline", status: 409, detail } }) }));
    await open(PRINTER_A);
    await userEvent.click(await screen.findByRole("button", { name: "Test print" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(detail);
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

  it("is disabled with a reason when a page printer is offline, unpolled or stale", async () => {
    for (const [over, reason] of [
      [{ online: false }, "Printer is not reachable"],
      [{ stale: true }, "Printer is not reachable"],
      [{ polled: false, online: null }, "Printer status unknown"],
    ] as const) {
      mockApi(routes(PAGE_PRINTER, pageStatus(PAGE_PRINTER.id, over)));
      const { unmount } = await open(PAGE_PRINTER);
      expect(await screen.findByText(reason)).toBeVisible();
      expect(screen.getByRole("button", { name: "Test print" })).toBeDisabled();
      unmount();
      vi.unstubAllGlobals();
    }
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
});
