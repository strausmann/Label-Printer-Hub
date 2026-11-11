import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderApp } from "../../test-utils";
import { apiErrorBody, job, mockApi, PAGE_PRINTER, pageStatus, respond, SHEET_TYPE, sheetRead } from "../test-api";
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
    [`GET /api/v1/jobs/${ID}`]: job(ID, PAGE_PRINTER.id, state, { template_key: null, payload: sheetPayload(), ...over }),
    "GET /api/v1/printers": [PAGE_PRINTER],
    ...extra,
  };
}

const TYPE_KEY = "avery-zweckform-l4736rev"; // the key the payload stores, not the label
const TYPE = { ...SHEET_TYPE, key: TYPE_KEY, vendor: "Avery Zweckform", product_codes: ["L4736REV-25"] };
const STOPPED_PRINTER = pageStatus(PAGE_PRINTER.id, { printer_state: "stopped", state_reasons: [{ keyword: "toner-empty", severity: "error", blocking: true }] });

const event = (atPrinter: string, reasons: string[] = []) => ({ kind: "sheet_page", atPrinter, reasons, summary: null });

describe("page job at the printer", () => {
  it("says the job is stopped at the printer, with the reason in words", async () => {
    mockApi(routes("printing"));
    const { queryClient } = await renderApp({ path: `/jobs/${ID}` });
    await screen.findByRole("heading", { level: 1, name: `Sheet ${CODE} · 3 labels` });
    act(() => void queryClient.setQueryData(pageJobStateKey(ID), event("stopped", ["printer-stopped", "toner-empty"])));
    expect(await screen.findByText("Stopped at the printer · toner empty")).toBeVisible();
  });

  it("names the printer's reason when the job only says printer-stopped", async () => {
    mockApi(routes("printing", {}, { [`GET /api/v1/printers/${PAGE_PRINTER.id}/status`]: STOPPED_PRINTER }));
    const { queryClient } = await renderApp({ path: `/jobs/${ID}` });
    await screen.findByRole("heading", { level: 1, name: `Sheet ${CODE} · 3 labels` });
    act(() => void queryClient.setQueryData(pageJobStateKey(ID), event("stopped", ["printer-stopped"])));
    expect(await screen.findByText("Stopped at the printer · toner empty")).toBeVisible();
  });

  it("uses the printer's blocking reasons when it does not report itself as stopped", async () => {
    const jam = pageStatus(PAGE_PRINTER.id, { printer_state: "idle", state_reasons: [{ keyword: "media-empty", severity: "error", blocking: true }, { keyword: "toner-low", severity: "warning", blocking: false }] });
    mockApi(routes("printing", {}, { [`GET /api/v1/printers/${PAGE_PRINTER.id}/status`]: jam }));
    const { queryClient } = await renderApp({ path: `/jobs/${ID}` });
    await screen.findByRole("heading", { level: 1, name: `Sheet ${CODE} · 3 labels` });
    act(() => void queryClient.setQueryData(pageJobStateKey(ID), event("stopped", ["printer-stopped"])));
    expect(await screen.findByText("Stopped at the printer · media empty")).toBeVisible();
  });

  it("stays at 'stopped' when neither the job nor the printer names a cause", async () => {
    const quiet = pageStatus(PAGE_PRINTER.id, { printer_state: "stopped", state_reasons: [] });
    mockApi(routes("printing", {}, { [`GET /api/v1/printers/${PAGE_PRINTER.id}/status`]: quiet }));
    const { queryClient } = await renderApp({ path: `/jobs/${ID}` });
    await screen.findByRole("heading", { level: 1, name: `Sheet ${CODE} · 3 labels` });
    act(() => void queryClient.setQueryData(pageJobStateKey(ID), event("stopped", ["printer-stopped"])));
    expect(await screen.findByText("Stopped at the printer")).toBeVisible();
  });

  it("does not ask for the printer status unless the job is stopped without a cause", async () => {
    const { calls } = mockApi(routes("printing"));
    const { queryClient } = await renderApp({ path: `/jobs/${ID}` });
    await screen.findByText("At the printer");
    act(() => void queryClient.setQueryData(pageJobStateKey(ID), event("stopped", ["toner-empty"])));
    await screen.findByText("Stopped at the printer · toner empty");
    expect(calls.some((c) => c.path === `/api/v1/printers/${PAGE_PRINTER.id}/status`)).toBe(false);
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

  it("says only 'at the printer' when no sub-state has been seen (a reload, or a job past the snapshot limit), and nothing once the job ended", async () => {
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
    // The page has no tape rows: the panel for tape jobs is not there, the printer is part of this section.
    expect(screen.queryByRole("region", { name: "What was printed" })).toBeNull();
    expect(await within(info).findByRole("link", { name: PAGE_PRINTER.name })).toBeVisible();
    expect(within(info).getByText("1")).toBeVisible(); // the sheet ID cell
  });

  it("labels a calibration page by the sheet type's name, not its key", async () => {
    const payload = { kind: "calibration_page", detail: { type_key: TYPE_KEY, version: 1 } };
    mockApi(routes("done", { payload }, { [`GET /api/v1/sheet-types/${TYPE_KEY}`]: TYPE }));
    await renderApp({ path: `/jobs/${ID}` });
    expect(await screen.findByRole("heading", { level: 1, name: "Calibration page · Avery Zweckform L4736REV-25 v1" })).toBeVisible();
    const info = screen.getByRole("region", { name: "Calibration page" });
    expect(within(info).getByText("Avery Zweckform L4736REV-25 v1")).toBeVisible();
    expect(within(info).queryByText("Sheet")).toBeNull();
  });

  it("falls back to the key when the sheet type cannot be read", async () => {
    const payload = { kind: "calibration_page", detail: { type_key: TYPE_KEY, version: 1 } };
    mockApi(routes("done", { payload }, { [`GET /api/v1/sheet-types/${TYPE_KEY}`]: respond(404, apiErrorBody("sheet_type_not_found", "gone")) }));
    await renderApp({ path: `/jobs/${ID}` });
    expect(await screen.findByRole("heading", { level: 1, name: `Calibration page · ${TYPE_KEY} v1` })).toBeVisible();
  });

  it("a tape job gets no page section", async () => {
    mockApi(routes("failed", { payload: { label_data: { title: "Cordless drill" } } }));
    await renderApp({ path: `/jobs/${ID}` });
    await screen.findByRole("heading", { level: 1, name: "Cordless drill" });
    expect(screen.queryByRole("region", { name: "Sheet page" })).toBeNull();
  });
});

describe("many cells", () => {
  it("folds a long cell list behind 'Show all n cells'", async () => {
    const cells = Array.from({ length: 120 }, (_, i) => ({ cell: i + 1 }));
    mockApi(routes("queued", { payload: sheetPayload({ cells }) }));
    await renderApp({ path: `/jobs/${ID}` });
    const info = await screen.findByRole("region", { name: "Sheet page" });
    expect(within(info).queryByText(/\b120\b/, { selector: "span.code" })).toBeNull();
    await userEvent.click(within(info).getByRole("button", { name: "Show all 120 cells" }));
    expect(within(info).getByText(/\b120\b/, { selector: "span.code" })).toBeVisible();
    await userEvent.click(within(info).getByRole("button", { name: "Show fewer" }));
    expect(within(info).queryByText(/\b120\b/, { selector: "span.code" })).toBeNull();
  });

  it("leaves a short list open", async () => {
    mockApi(routes("queued"));
    await renderApp({ path: `/jobs/${ID}` });
    const info = await screen.findByRole("region", { name: "Sheet page" });
    expect(within(info).queryByRole("button", { name: /Show/ })).toBeNull();
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
      mockApi(routes(state, {}, { [`GET /api/v1/sheets/${CODE}`]: sheet() }));
      await renderApp({ path: `/jobs/${ID}` });
      expect(await screen.findByText("Not confirmed")).toBeVisible();
      const info = screen.getByRole("region", { name: "Sheet page" });
      // Cell 5 is unconfirmed too, but another job's.
      expect(within(info).getByText("4", { selector: "span.code" })).toBeVisible();
      expect(within(info).getByRole("link", { name: "Settle the cells on the sheet" })).toHaveAttribute("href", `/sheets/${CODE}`);
    });
  }

  it("shows no such block when the job's cells are settled, or the sheet cannot be read", async () => {
    const settled = sheetRead(CODE, { used: [4, 5, 6] });
    mockApi(routes("failed", {}, { [`GET /api/v1/sheets/${CODE}`]: settled }));
    const { unmount } = await renderApp({ path: `/jobs/${ID}` });
    await screen.findByRole("region", { name: "Sheet page" });
    await waitFor(() => expect(screen.queryByText("Not confirmed")).toBeNull());
    unmount();
    mockApi(routes("failed", {}, { [`GET /api/v1/sheets/${CODE}`]: respond(404, apiErrorBody("sheet_not_found", "gone")) }));
    await renderApp({ path: `/jobs/${ID}` });
    await screen.findByRole("region", { name: "Sheet page" });
    expect(screen.queryByText("Not confirmed")).toBeNull();
  });

  it("does not offer to settle cells of a discarded sheet", async () => {
    const s = sheet();
    mockApi(routes("failed", {}, { [`GET /api/v1/sheets/${CODE}`]: { ...s, state: "discarded", discarded_at: "2026-11-04T09:00:00Z" } }));
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
    const { calls } = mockApi(routes("failed", {}, { [`POST /api/v1/jobs/${ID}/retry`]: created, [`GET /api/v1/jobs/${NEW}`]: created }));
    const { router } = await renderApp({ path: `/jobs/${ID}` });
    await userEvent.click(await screen.findByRole("button", { name: "Retry" }));
    await waitFor(() => expect(router.state.location.pathname).toBe(`/jobs/${NEW}`));
    expect(calls.some((c) => c.method === "POST" && c.path === `/api/v1/jobs/${ID}/retry`)).toBe(true);
  });

  const retryRefused = async (status: number, code: string, detail?: Record<string, unknown>) => {
    mockApi(routes("failed", {}, { [`POST /api/v1/jobs/${ID}/retry`]: respond(status, apiErrorBody(code, "x", detail)) }));
    await renderApp({ path: `/jobs/${ID}` });
    await userEvent.click(await screen.findByRole("button", { name: "Retry" }));
    return screen.findByRole("alert");
  };

  it("409 cells_unconfirmed names the cells and links to the sheet", async () => {
    const alert = await retryRefused(409, "cells_unconfirmed", { cells: [4, 5] });
    expect(alert).toHaveTextContent("Cells 4, 5 may or may not have been printed");
    expect(within(alert).getByRole("link", { name: `Open ${CODE}` })).toHaveAttribute("href", `/sheets/${CODE}`);
  });

  it("409 cells_taken says which cells are in use now", async () => {
    expect(await retryRefused(409, "cells_taken", { cells: [6] })).toHaveTextContent("Cells 6 are in use by something else now");
  });

  it("409 job_not_retryable", async () => {
    expect(await retryRefused(409, "job_not_retryable")).toHaveTextContent("This job cannot be retried: nothing is left to print.");
  });

  it("409 printer_disabled", async () => {
    expect(await retryRefused(409, "printer_disabled")).toHaveTextContent("The printer is switched off.");
  });

  // The queue refusals arrive as problems (`detail.type`, hyphen forms), not as error codes.
  const problemRefused = async (status: number, type: string) => {
    mockApi(routes("failed", {}, { [`POST /api/v1/jobs/${ID}/retry`]: respond(status, { detail: { type, title: "Title", detail: "English detail" } }) }));
    await renderApp({ path: `/jobs/${ID}` });
    await userEvent.click(await screen.findByRole("button", { name: "Retry" }));
    return screen.findByRole("alert");
  };

  it("409 printer-unavailable (problem shape) says the queue does not know the printer yet", async () => {
    expect(await problemRefused(409, "printer-unavailable")).toHaveTextContent("The print queue does not know this printer yet.");
  });

  it("422 job-not-retryable (problem shape) says the stored page cannot be drawn", async () => {
    expect(await problemRefused(422, "job-not-retryable")).toHaveTextContent("its stored page can no longer be drawn");
  });

  it("409 tray_unknown has its own words", async () => {
    expect(await retryRefused(409, "tray_unknown")).toHaveTextContent("The tray this job used is not available any more.");
  });

  it("403 insufficient_scope names the key a retry needs", async () => {
    expect(await retryRefused(403, "insufficient_scope")).toHaveTextContent("Retrying needs a print or admin key.");
  });

  it("403 printer_not_allowed", async () => {
    expect(await retryRefused(403, "printer_not_allowed")).toHaveTextContent("This key may not use this printer.");
  });

  it("an unknown error ends in the plain sentence", async () => {
    expect(await retryRefused(500, "boom")).toHaveTextContent("The job could not be retried.");
  });

  it("a network error says the hub could not be reached", async () => {
    mockApi(routes("failed", {}, { [`POST /api/v1/jobs/${ID}/retry`]: () => Promise.reject(new TypeError("Failed to fetch")) }));
    await renderApp({ path: `/jobs/${ID}` });
    await userEvent.click(await screen.findByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The hub could not be reached. Try again.");
  });

  it("cancel is offered while a page job prints, and the text says the printer was asked", async () => {
    const { calls } = mockApi(routes("printing", {}, { [`POST /api/v1/jobs/${ID}/cancel`]: job(ID, PAGE_PRINTER.id, "printing", { payload: sheetPayload() }) }));
    await renderApp({ path: `/jobs/${ID}` });
    await userEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    expect(await screen.findByText("Asked the printer to cancel. The cells are settled when it reports.")).toBeVisible();
    expect(calls.some((c) => c.method === "POST" && c.path === `/api/v1/jobs/${ID}/cancel`)).toBe(true);
  });

  it("the Cancel button is gone once the printer was asked, so it cannot be pressed twice", async () => {
    mockApi(routes("printing", {}, { [`POST /api/v1/jobs/${ID}/cancel`]: job(ID, PAGE_PRINTER.id, "printing", { payload: sheetPayload() }) }));
    await renderApp({ path: `/jobs/${ID}` });
    await userEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    await screen.findByText(/Asked the printer to cancel/);
    expect(screen.queryByRole("button", { name: "Cancel" })).toBeNull();
  });

  it("a refused cancel says so; a network error says the hub could not be reached", async () => {
    mockApi(routes("printing", {}, { [`POST /api/v1/jobs/${ID}/cancel`]: respond(409, apiErrorBody("job_not_cancellable", "x")) }));
    const { unmount } = await renderApp({ path: `/jobs/${ID}` });
    await userEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The job could not be cancelled.");
    expect(screen.queryByText(/Asked the printer to cancel/)).toBeNull();
    unmount();
    mockApi(routes("printing", {}, { [`POST /api/v1/jobs/${ID}/cancel`]: () => Promise.reject(new TypeError("Failed to fetch")) }));
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
    mockApi({ "GET /api/v1/printers": [PAGE_PRINTER], "GET /api/v1/jobs": [page] });
    const { queryClient } = await renderApp({ path: "/jobs" });
    expect(await screen.findByRole("link", { name: `Sheet ${CODE} · 3 labels` })).toBeVisible();
    expect(screen.getByText("At the printer")).toBeVisible();
    act(() => void queryClient.setQueryData(pageJobStateKey(ID), event("stopped", ["media-empty"])));
    expect(await screen.findByText("Stopped at the printer · media empty")).toBeVisible();
  });
});

describe("test page job", () => {
  it("shows the tray's label from the printer, not its key, and falls back to the key", async () => {
    mockApi(
      routes(
        "queued",
        { payload: { kind: "test_page", media: "A4", tray: "main", detail: {} } },
        { [`GET /api/v1/printers/${PAGE_PRINTER.id}/status`]: pageStatus(PAGE_PRINTER.id) },
      ),
    );
    await renderApp({ path: `/jobs/${ID}` });
    await screen.findByRole("heading", { level: 1, name: "Test page · Main tray" });
    expect(within(screen.getByRole("region", { name: "Test page" })).getByText("Main tray")).toBeVisible();
  });

  it("does not talk about cells when a printing test page is cancelled", async () => {
    mockApi(routes("printing", { payload: { kind: "test_page", media: "A4", tray: "main", detail: {} } }, { [`POST /api/v1/jobs/${ID}/cancel`]: job(ID, PAGE_PRINTER.id, "printing") }));
    await renderApp({ path: `/jobs/${ID}` });
    await userEvent.click(await screen.findByRole("button", { name: /Cancel/ }));
    expect(await screen.findByText("Asked the printer to cancel.")).toBeVisible();
    expect(screen.queryByText(/cells are settled/)).toBeNull();
  });

  it("is titled by its tray and shows the tray and paper size, not sheet fields", async () => {
    mockApi(routes("queued", { payload: { kind: "test_page", media: "A4", tray: "bypass", detail: { printer_name: "Office laser" } } }));
    await renderApp({ path: `/jobs/${ID}` });
    await screen.findByRole("heading", { level: 1, name: "Test page · bypass" });
    const section = screen.getByRole("region", { name: "Test page" });
    expect(within(section).getByText("bypass")).toBeVisible();
    expect(within(section).getByText("A4")).toBeVisible();
    expect(within(section).queryByText("Sheet")).toBeNull();
  });
});
