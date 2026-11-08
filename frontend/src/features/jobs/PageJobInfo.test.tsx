import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderApp } from "../../test-utils";
import { apiErrorBody, job, mockApi, PAGE_PRINTER, respond, sheetRead } from "../test-api";
import { pageJobStateKey } from "./pageJobState";

afterEach(() => vi.unstubAllGlobals());

const ID = "dddddddd-0000-4000-8000-000000000001";
const NEW = "dddddddd-0000-4000-8000-000000000002";
const CODE = "L4736-0002";

const sheetPayload = (over: Record<string, unknown> = {}) => ({
  kind: "sheet_page",
  detail: { sheet_code: CODE, cells: [{ cell: 4 }, { cell: 5 }, { cell: 6 }], id_cell: { cell: 1 }, job_summary: { sheet_code: CODE, cell_count: 3 }, ...over },
});

function routes(state: string, over: Record<string, unknown> = {}, extra: Record<string, unknown> = {}) {
  return {
    [`GET /api/jobs/${ID}`]: job(ID, PAGE_PRINTER.id, state, { template_key: null, payload: sheetPayload(), ...over }),
    "GET /api/printers": [PAGE_PRINTER],
    ...extra,
  };
}

const event = (atPrinter: string, reasons: string[] = []) => ({ kind: "sheet_page", atPrinter, reasons, summary: null });

describe("page job at the printer", () => {
  it("says the job is stopped at the printer, with the reason in words", async () => {
    mockApi(routes("printing"));
    const { queryClient } = await renderApp({ path: `/jobs/${ID}` });
    await screen.findByRole("heading", { level: 1, name: `Sheet ${CODE} · 3 labels` });
    act(() => void queryClient.setQueryData(pageJobStateKey(ID), event("stopped", ["printer-stopped", "toner-empty"])));
    expect(await screen.findByText("Stopped at the printer · toner empty")).toBeVisible();
  });

  it("follows the sub-state: waiting, then printing", async () => {
    mockApi(routes("printing"));
    const { queryClient } = await renderApp({ path: `/jobs/${ID}` });
    const info = await screen.findByRole("region", { name: "Sheet page" });
    act(() => void queryClient.setQueryData(pageJobStateKey(ID), event("waiting")));
    expect(await within(info).findByText("Waiting at the printer")).toBeVisible();
    act(() => void queryClient.setQueryData(pageJobStateKey(ID), event("printing")));
    expect(await within(info).findByText("Printing")).toBeVisible();
    expect(within(info).queryByText("Waiting at the printer")).toBeNull();
  });

  it("says only 'at the printer' when no sub-state has been seen, and nothing once the job ended", async () => {
    mockApi(routes("printing"));
    const { unmount } = await renderApp({ path: `/jobs/${ID}` });
    expect(await screen.findByText("At the printer")).toBeVisible();
    unmount();
    mockApi(routes("done"));
    await renderApp({ path: `/jobs/${ID}` });
    await screen.findByRole("region", { name: "Sheet page" });
    expect(screen.queryByText("At the printer")).toBeNull();
  });

  it("shows the sheet as a link, the labels and the cells", async () => {
    mockApi(routes("queued"));
    await renderApp({ path: `/jobs/${ID}` });
    const info = await screen.findByRole("region", { name: "Sheet page" });
    expect(within(info).getByRole("link", { name: CODE })).toHaveAttribute("href", `/sheets/${CODE}`);
    expect(within(info).getByText("4, 5, 6")).toBeVisible();
    // The tape rows (title, tape width, copies) have no meaning for a page and are left out.
    const printed = screen.getByRole("region", { name: "What was printed" });
    expect(within(printed).queryByText("Tape")).toBeNull();
    expect(within(printed).getByText("Printer")).toBeVisible();
    expect(within(info).getByText("1")).toBeVisible(); // the sheet ID cell
  });

  it("labels a calibration page by its sheet type", async () => {
    const payload = { kind: "calibration_page", detail: { type_key: "L4736REV", version: 1 } };
    mockApi(routes("done", { payload }));
    await renderApp({ path: `/jobs/${ID}` });
    expect(await screen.findByRole("heading", { level: 1, name: "Calibration page · L4736REV v1" })).toBeVisible();
    const info = screen.getByRole("region", { name: "Calibration page" });
    expect(within(info).getByText("L4736REV v1")).toBeVisible();
    expect(within(info).queryByText("Sheet")).toBeNull();
  });

  it("a tape job gets no page section", async () => {
    mockApi(routes("failed", { payload: { label_data: { title: "Cordless drill" } } }));
    await renderApp({ path: `/jobs/${ID}` });
    await screen.findByRole("heading", { level: 1, name: "Cordless drill" });
    expect(screen.queryByRole("region", { name: "Sheet page" })).toBeNull();
  });
});

describe("an interrupted page job", () => {
  const sheet = () => {
    const s = sheetRead(CODE, { unconfirmed: [4, 5], used: [1] });
    s.cells = s.cells.map((c) => (c.state === "unconfirmed" && c.cell === 4 ? { ...c, job_id: ID } : c.state === "unconfirmed" ? { ...c, job_id: "other-job" } : c));
    return s;
  };

  for (const state of ["failed", "failed_restart", "cancelled"]) {
    it(`lists the unconfirmed cells of a ${state} job and links to resolve them`, async () => {
      mockApi(routes(state, {}, { [`GET /api/sheets/${CODE}`]: sheet() }));
      await renderApp({ path: `/jobs/${ID}` });
      expect(await screen.findByText("Not confirmed")).toBeVisible();
      const info = screen.getByRole("region", { name: "Sheet page" });
      // Cell 5 is unconfirmed too, but another job's.
      expect(within(info).getByText("4", { selector: "p.code" })).toBeVisible();
      expect(within(info).getByRole("link", { name: "Settle the cells on the sheet" })).toHaveAttribute("href", `/sheets/${CODE}`);
    });
  }

  it("shows no such block when the job's cells are settled, or the sheet cannot be read", async () => {
    const settled = sheetRead(CODE, { used: [4, 5, 6] });
    mockApi(routes("failed", {}, { [`GET /api/sheets/${CODE}`]: settled }));
    const { unmount } = await renderApp({ path: `/jobs/${ID}` });
    await screen.findByRole("region", { name: "Sheet page" });
    await waitFor(() => expect(screen.queryByText("Not confirmed")).toBeNull());
    unmount();
    mockApi(routes("failed", {}, { [`GET /api/sheets/${CODE}`]: respond(404, apiErrorBody("sheet_not_found", "gone")) }));
    await renderApp({ path: `/jobs/${ID}` });
    await screen.findByRole("region", { name: "Sheet page" });
    expect(screen.queryByText("Not confirmed")).toBeNull();
  });

  it("does not offer to settle cells of a discarded sheet", async () => {
    const s = sheet();
    mockApi(routes("failed", {}, { [`GET /api/sheets/${CODE}`]: { ...s, state: "discarded", discarded_at: "2026-11-04T09:00:00Z" } }));
    await renderApp({ path: `/jobs/${ID}` });
    expect(await screen.findByText(/cannot be settled any more/)).toBeVisible();
    expect(screen.queryByRole("link", { name: "Settle the cells on the sheet" })).toBeNull();
  });
});

describe("retry and cancel of page jobs", () => {
  it("a cancelled page job can be retried; a cancelled tape job cannot", async () => {
    mockApi(routes("cancelled"));
    const { unmount } = await renderApp({ path: `/jobs/${ID}` });
    expect(await screen.findByRole("button", { name: "Retry" })).toBeVisible();
    unmount();
    mockApi(routes("cancelled", { payload: {} }));
    await renderApp({ path: `/jobs/${ID}` });
    await screen.findByRole("heading", { level: 1 });
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
  });

  it("retry opens the new job", async () => {
    const created = job(NEW, PAGE_PRINTER.id, "queued", { template_key: null, payload: sheetPayload() });
    const { calls } = mockApi(routes("failed", {}, { [`POST /api/jobs/${ID}/retry`]: created, [`GET /api/jobs/${NEW}`]: created }));
    const { router } = await renderApp({ path: `/jobs/${ID}` });
    await userEvent.click(await screen.findByRole("button", { name: "Retry" }));
    await waitFor(() => expect(router.state.location.pathname).toBe(`/jobs/${NEW}`));
    expect(calls.some((c) => c.method === "POST" && c.path === `/api/jobs/${ID}/retry`)).toBe(true);
  });

  const retryRefused = async (status: number, code: string, detail?: Record<string, unknown>) => {
    mockApi(routes("failed", {}, { [`POST /api/jobs/${ID}/retry`]: respond(status, apiErrorBody(code, "x", detail)) }));
    await renderApp({ path: `/jobs/${ID}` });
    await userEvent.click(await screen.findByRole("button", { name: "Retry" }));
    return screen.findByRole("alert");
  };

  it("409 cells_unconfirmed names the cells and links to the sheet", async () => {
    const alert = await retryRefused(409, "cells_unconfirmed", { cells: [4, 5] });
    expect(alert).toHaveTextContent("Cells 4, 5 may or may not have been printed");
    expect(within(alert).getByRole("link", { name: `Open ${CODE}` })).toHaveAttribute("href", `/sheets/${CODE}`);
  });

  it("409 cells_taken, job_not_retryable and printer_disabled say what happened", async () => {
    expect(await retryRefused(409, "cells_taken", { cells: [6] })).toHaveTextContent("Cells 6 are in use by something else now");
  });

  it("409 job_not_retryable", async () => {
    expect(await retryRefused(409, "job_not_retryable")).toHaveTextContent("This job cannot be retried: nothing is left to print.");
  });

  it("409 printer_disabled", async () => {
    expect(await retryRefused(409, "printer_disabled")).toHaveTextContent("The printer is switched off.");
  });

  it("an unknown error ends in the plain sentence", async () => {
    expect(await retryRefused(500, "boom")).toHaveTextContent("The job could not be retried.");
  });

  it("a network error says the hub could not be reached", async () => {
    mockApi(routes("failed", {}, { [`POST /api/jobs/${ID}/retry`]: () => Promise.reject(new TypeError("Failed to fetch")) }));
    await renderApp({ path: `/jobs/${ID}` });
    await userEvent.click(await screen.findByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The hub could not be reached. Try again.");
  });

  it("cancel is offered while a page job prints, and the text says the printer was asked", async () => {
    const { calls } = mockApi(routes("printing", {}, { [`POST /api/jobs/${ID}/cancel`]: job(ID, PAGE_PRINTER.id, "printing", { payload: sheetPayload() }) }));
    await renderApp({ path: `/jobs/${ID}` });
    await userEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    expect(await screen.findByText("Asked the printer to cancel. The cells are settled when it reports.")).toBeVisible();
    expect(calls.some((c) => c.method === "POST" && c.path === `/api/jobs/${ID}/cancel`)).toBe(true);
  });

  it("a refused cancel says so; a network error says the hub could not be reached", async () => {
    mockApi(routes("printing", {}, { [`POST /api/jobs/${ID}/cancel`]: respond(409, apiErrorBody("job_not_cancellable", "x")) }));
    const { unmount } = await renderApp({ path: `/jobs/${ID}` });
    await userEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The job could not be cancelled.");
    expect(screen.queryByText(/Asked the printer to cancel/)).toBeNull();
    unmount();
    mockApi(routes("printing", {}, { [`POST /api/jobs/${ID}/cancel`]: () => Promise.reject(new TypeError("Failed to fetch")) }));
    await renderApp({ path: `/jobs/${ID}` });
    await userEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The hub could not be reached. Try again.");
  });

  it("a tape job in print has no Cancel", async () => {
    mockApi(routes("printing", { payload: {} }));
    await renderApp({ path: `/jobs/${ID}` });
    await screen.findByRole("heading", { level: 1 });
    expect(screen.queryByRole("button", { name: "Cancel" })).toBeNull();
  });
});

describe("job list", () => {
  it("titles page jobs and shows where a printing one stands", async () => {
    const page = job(ID, PAGE_PRINTER.id, "printing", { template_key: null, payload: sheetPayload() });
    mockApi({ "GET /api/printers": [PAGE_PRINTER], "GET /api/jobs": [page] });
    const { queryClient } = await renderApp({ path: "/jobs" });
    expect(await screen.findByRole("link", { name: `Sheet ${CODE} · 3 labels` })).toBeVisible();
    expect(screen.getByText("At the printer")).toBeVisible();
    act(() => void queryClient.setQueryData(pageJobStateKey(ID), event("stopped", ["media-empty"])));
    expect(await screen.findByText("Stopped at the printer · media empty")).toBeVisible();
  });
});
