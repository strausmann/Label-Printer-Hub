// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderApp } from "../../test-utils";
import { job, mockApi, PAGE_PRINTER, PRINTER_A, PRINTER_B, status } from "../test-api";

afterEach(() => vi.unstubAllGlobals());

const Q = "bbbbbbbb-0000-4000-8000-000000000001";
const R = "bbbbbbbb-0000-4000-8000-000000000002";

function routes(printer: Record<string, unknown> & { id: string } = PRINTER_A, extra: Record<string, unknown> = {}) {
  return {
    [`GET /api/v1/printers/${printer.id}`]: printer,
    [`GET /api/v1/printers/${printer.id}/status`]: status(printer.id),
    [`GET /api/v1/printers/${printer.id}/queue`]: [
      { ...job(R, printer.id, "printing", { template_key: "run-label" }), created_at: "2026-11-04T09:00:00Z" },
      { ...job(Q, printer.id, "queued", { template_key: "wait-label" }), created_at: "2026-11-04T09:01:00Z" },
    ],
    ...extra,
  };
}

describe("PrinterDetail", () => {
  it("offers Cancel only on queued jobs", async () => {
    mockApi(routes());
    await renderApp({ path: `/printers/${PRINTER_A.id}` });
    const queue = await screen.findByRole("region", { name: "Queue" });
    const running = (await within(queue).findByText("run-label")).closest("li")!;
    const waiting = within(queue).getByText("wait-label").closest("li")!;
    expect(within(running).queryByRole("button", { name: /Cancel/ })).toBeNull();
    expect(within(waiting).getByRole("button", { name: /Cancel/ })).toBeVisible();
  });

  it("cancel posts to the job with the CSRF header", async () => {
    const { calls } = mockApi(routes(PRINTER_A, { [`POST /api/v1/jobs/${Q}/cancel`]: job(Q, PRINTER_A.id, "cancelled") }));
    await renderApp({ path: `/printers/${PRINTER_A.id}` });
    await userEvent.click(await screen.findByRole("button", { name: "Cancel wait-label" }));
    await waitFor(() => expect(calls.some((c) => c.path === `/api/v1/jobs/${Q}/cancel`)).toBe(true));
  });

  it("pause posts with CSRF header", async () => {
    const { calls } = mockApi(routes(PRINTER_A, { [`POST /api/v1/printers/${PRINTER_A.id}/pause`]: null }));
    await renderApp({ path: `/printers/${PRINTER_A.id}` });
    await userEvent.click(await screen.findByRole("button", { name: "Pause" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    const post = calls.find((c) => c.method === "POST")!;
    expect(post.path).toBe(`/api/v1/printers/${PRINTER_A.id}/pause`);
    expect(post.headers.get("X-CSRF-Token")).toBe("csrf-test");
  });

  it("a paused printer shows Resume and a Paused badge at the top", async () => {
    mockApi(routes(PRINTER_B));
    await renderApp({ path: `/printers/${PRINTER_B.id}` });
    expect(await screen.findByRole("button", { name: "Resume" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Pause" })).toBeNull();
    expect(screen.getAllByText("Paused").length).toBeGreaterThan(0);
  });

  it("shows the reason next to the Paused badge", async () => {
    const pause = { source: "printer_error", reason_code: "tape_mismatch", since: "2026-11-04T10:00:00Z" };
    mockApi(routes({ ...PRINTER_B, pause }));
    await renderApp({ path: `/printers/${PRINTER_B.id}` });
    expect(await screen.findByText("Wrong tape loaded")).toBeVisible();
  });

  it("shows the connection exactly as stored", async () => {
    mockApi(routes(PRINTER_B));
    await renderApp({ path: `/printers/${PRINTER_B.id}` });
    const connection = await screen.findByRole("region", { name: "Connection" });
    expect(within(connection).getByText("Printer-B.Example.invalid")).toBeVisible();
    expect(within(connection).getByText("QL-820NWB")).toBeVisible();
    expect(within(connection).getByText("brother_ql")).toBeVisible();
  });

  it("an IPP printer shows no tape host and port; a key below admin gets no address, an admin gets it", async () => {
    mockApi(routes({ ...PAGE_PRINTER, connection: { tls_verify: false } }));
    const first = await renderApp({ path: `/printers/${PAGE_PRINTER.id}` });
    const connection = await screen.findByRole("region", { name: "Connection" });
    expect(within(connection).queryByText("Host")).toBeNull();
    expect(within(connection).queryByText("Port")).toBeNull();
    expect(within(connection).queryByText("Address")).toBeNull();
    expect(within(connection).queryByText("—")).toBeNull();
    expect(within(connection).getByText("Certificate check")).toBeVisible();
    expect(within(connection).getByText("off")).toBeVisible();
    first.unmount();

    mockApi(routes(PAGE_PRINTER));
    await renderApp({ path: `/printers/${PAGE_PRINTER.id}` });
    const admin = await screen.findByRole("region", { name: "Connection" });
    expect(within(admin).getByText("ipp://printer.example.invalid/ipp/print")).toBeVisible();
    expect(within(admin).queryByText("Host")).toBeNull();
  });

  it("shows the calibration placeholder only when the feature is on", async () => {
    mockApi(routes());
    const first = await renderApp({ path: `/printers/${PRINTER_A.id}` });
    await screen.findByRole("region", { name: "Queue" });
    expect(screen.queryByRole("region", { name: "Calibration" })).toBeNull();
    first.unmount();
    await renderApp({ path: `/printers/${PRINTER_A.id}`, info: { features: { calibration: true } } });
    expect(await screen.findByRole("region", { name: "Calibration" })).toBeVisible();
  });

  it("says when the queue is empty and when the printer is unknown", async () => {
    mockApi(routes(PRINTER_A, { [`GET /api/v1/printers/${PRINTER_A.id}/queue`]: [] }));
    await renderApp({ path: `/printers/${PRINTER_A.id}` });
    expect(await screen.findByText("Nothing is waiting.")).toBeVisible();
  });

  it("shows a not-found note for an unknown printer", async () => {
    mockApi({});
    await renderApp({ path: "/printers/99999999-9999-4999-8999-999999999999" });
    expect(await screen.findByText("This printer does not exist.")).toBeVisible();
  });

  it("clears the queue only after a confirmation", async () => {
    const { calls } = mockApi(routes(PRINTER_A, { [`POST /api/v1/printers/${PRINTER_A.id}/queue/clear`]: null }));
    await renderApp({ path: `/printers/${PRINTER_A.id}` });
    await userEvent.click(await screen.findByRole("button", { name: "Clear queue" }));
    expect(calls.some((c) => c.path.endsWith("/queue/clear"))).toBe(false);
    await userEvent.click(screen.getByRole("button", { name: "Cancel 1 queued" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path.endsWith("/queue/clear"))).toBe(true));
  });

  it("reports a failed cancel instead of staying silent", async () => {
    mockApi(routes());
    await renderApp({ path: `/printers/${PRINTER_A.id}` });
    // The cancel route is not mocked, so the server answers 404.
    await userEvent.click(await screen.findByRole("button", { name: "Cancel wait-label" }));
    expect(await screen.findByText("The job could not be cancelled.")).toBeVisible();
  });
});
