import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { dismissWatch, recordJobEvent, resetPrintWatch, watchPrint } from "../features/jobs/printWatch";
import { job, mockApi, PRINTER_A } from "../features/test-api";
import { renderApp } from "../test-utils";
import { AUTO_DISMISS_MS, MAX_VISIBLE } from "./PrintToasts";

const A = "aaaaaaaa-0000-4000-8000-000000000001";
const B = "aaaaaaaa-0000-4000-8000-000000000002";
const C = "aaaaaaaa-0000-4000-8000-000000000003";
const NEW = "aaaaaaaa-0000-4000-8000-000000000009";

const event = (jobId: string, to: string, extra: Record<string, unknown> = {}) =>
  act(() => recordJobEvent({ job_id: jobId, from_state: "queued", to_state: to, queue_depth: 1, error_code: null, ...extra }));
const watch = (kind: "item" | "cart" | "sheet" | "calibration" | "test", jobIds: string[]) =>
  act(() => void watchPrint({ kind, printerId: PRINTER_A.id, jobIds }));
const region = () => screen.getByRole("region", { name: "Print status" });

// jsdom has no PointerEvent: a mouse event that carries the fields the swipe reads stands in for it.
class FakePointerEvent extends MouseEvent {
  pointerId: number;
  pointerType: string;
  constructor(type: string, init: MouseEventInit & { pointerId?: number; pointerType?: string } = {}) {
    super(type, init);
    this.pointerId = init.pointerId ?? 0;
    this.pointerType = init.pointerType ?? "mouse";
  }
}
vi.stubGlobal("PointerEvent", FakePointerEvent);

let calls: ReturnType<typeof mockApi>["calls"];

beforeEach(async () => {
  resetPrintWatch();
  ({ calls } = mockApi({
    "GET /api/v1/printers": [PRINTER_A],
    [`GET /api/v1/jobs/${A}`]: job(A, PRINTER_A.id, "failed", { error: "Tape jam at the cutter." }),
    [`POST /api/v1/jobs/${A}/retry`]: job(NEW, PRINTER_A.id, "queued"),
  }));
  await renderApp({ path: "/about" });
});
afterEach(() => {
  vi.useRealTimers();
  resetPrintWatch();
});

describe("print notifications", () => {
  it("follows queued -> printing -> done and leaves by itself", async () => {
    watch("item", [A]);
    expect(await within(region()).findByText(/Queued/)).toBeVisible();
    expect(within(region()).getByText("Label")).toBeVisible();
    expect(await within(region()).findByText(/on Workshop PT-P750W/)).toBeVisible();
    event(A, "printing");
    expect(within(region()).getByText("Printing")).toBeVisible();
    // The dismiss timer starts when the entry turns done, so the clock is faked before that event.
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    event(A, "done");
    expect(within(region()).getByText("Done")).toBeVisible();
    act(() => void vi.advanceTimersByTime(AUTO_DISMISS_MS - 100));
    expect(within(region()).getByText("Done")).toBeVisible();
    act(() => void vi.advanceTimersByTime(200));
    expect(screen.queryByText("Done")).toBeNull();
  });

  it("keeps a failed print with the hub's error and a Retry that follows the new job", async () => {
    watch("test", [A]);
    event(A, "failed", { error_code: "printer_offline" });
    const alert = region();
    expect(await within(alert).findByText(/The printer could not be reached/)).toBeVisible();
    expect(within(alert).getByText("Failed")).toBeVisible();
    // The failure sits in the assertive live region, progress in the polite one.
    expect(within(alert).getByText("Failed").closest("[aria-live]")?.getAttribute("aria-live")).toBe("assertive");
    fireEvent.click(await within(alert).findByRole("button", { name: "Retry" }));
    expect(await within(alert).findByText(/Queued/)).toBeVisible();
    expect(calls.some((c) => c.method === "POST" && c.path === `/api/v1/jobs/${A}/retry`)).toBe(true);
    expect(within(alert).queryByText("Failed")).toBeNull();
    expect(within(alert).getByText(/Queued/).closest("[aria-live]")?.getAttribute("aria-live")).toBe("polite");
  });

  it("shows batch progress and the sheet's pages", () => {
    watch("cart", [A, B, C]);
    event(A, "done");
    event(B, "printing");
    expect(within(region()).getByText(/1 of 3 items/)).toBeVisible();
    watch("sheet", [NEW, "aaaaaaaa-0000-4000-8000-00000000000a"]);
    expect(within(region()).getByText(/0 of 2 pages/)).toBeVisible();
  });

  it("gives concurrent prints their own entries", () => {
    watch("item", [A]);
    watch("calibration", [B]);
    event(B, "printing");
    expect(within(region()).getAllByRole("listitem")).toHaveLength(2);
    expect(within(region()).getByText("Calibration page")).toBeVisible();
  });

  it("closes with the button and with Escape", () => {
    watch("item", [A]);
    watch("item", [B]);
    fireEvent.click(within(region()).getAllByRole("button", { name: "Dismiss notification" })[0]!);
    expect(within(region()).getAllByRole("listitem")).toHaveLength(1);
    fireEvent.keyDown(within(region()).getByRole("listitem"), { key: "Escape" });
    expect(within(region()).queryAllByRole("listitem")).toHaveLength(0);
  });

  it("is dismissed by a swipe, not by a short drag", () => {
    watch("item", [A]);
    const card = within(region()).getByRole("listitem");
    card.setPointerCapture = vi.fn();
    vi.useFakeTimers({ toFake: ["Date"] });
    fireEvent.pointerDown(card, { pointerId: 1, pointerType: "touch", clientX: 200 });
    vi.setSystemTime(Date.now() + 900);
    fireEvent.pointerUp(card, { pointerId: 1, pointerType: "touch", clientX: 190 });
    expect(within(region()).getAllByRole("listitem")).toHaveLength(1);
    fireEvent.pointerDown(card, { pointerId: 2, pointerType: "touch", clientX: 200 });
    vi.setSystemTime(Date.now() + 100);
    fireEvent.pointerUp(card, { pointerId: 2, pointerType: "touch", clientX: 40 });
    expect(within(region()).queryAllByRole("listitem")).toHaveLength(0);
  });

  it("survives navigation: the stack is part of the shell", async () => {
    watch("item", [A]);
    event(A, "printing");
    fireEvent.click(screen.getAllByRole("link", { name: "Jobs" })[0]!);
    expect(await screen.findByRole("heading", { level: 1, name: "Jobs" })).toBeVisible();
    event(A, "done");
    expect(within(region()).getByText("Done")).toBeVisible();
  });

  it("dismissing an unknown entry changes nothing", () => {
    watch("item", [A]);
    act(() => dismissWatch("print-unknown"));
    expect(within(region()).getAllByRole("listitem")).toHaveLength(1);
  });

  it("says Queued without a number: no job position is known", () => {
    watch("item", [A]);
    event(A, "queued", { queue_depth: 5 });
    expect(within(region()).getByText("Queued")).toBeVisible();
    expect(within(region()).queryByText(/ahead/)).toBeNull();
  });

  it("shows a paused job as paused", () => {
    watch("item", [A]);
    event(A, "paused");
    expect(within(region()).getByText("Paused")).toBeVisible();
  });

  it("explains a failure by its code in the app's words, an unknown code with the code, never the raw hub text", async () => {
    watch("test", [A]);
    event(A, "failed", { error_code: "printer_cover_open" });
    expect(await within(region()).findByText("The printer cover is open. Close it and retry.")).toBeVisible();
    expect(within(region()).queryByText(/Tape jam/)).toBeNull();
    watch("test", [B]);
    event(B, "failed", { error_code: "weird_new_code" });
    expect(await within(region()).findByText("The print failed (error code weird_new_code).")).toBeVisible();
  });

  it("takes the code from the job record when no frame carried one", async () => {
    mockApi({
      "GET /api/v1/printers": [PRINTER_A],
      [`GET /api/v1/jobs/${A}`]: job(A, PRINTER_A.id, "failed", { error: "ipp_aborted: The printer aborted the job before printing." }),
    });
    watch("test", [A]);
    event(A, "failed");
    expect(await within(region()).findByText("The printer aborted the job before printing.")).toBeVisible();
  });

  it("caps the stack: five failures show three cards and a summary, closing one brings the next up", () => {
    const ids = ["1", "2", "3", "4", "5"].map((n) => `aaaaaaaa-0000-4000-8000-00000000010${n}`);
    ids.forEach((id) => {
      watch("test", [id]);
      event(id, "failed", { error_code: "ipp_busy" });
    });
    const cards = () => within(region()).getAllByRole("listitem").filter((li) => li.getAttribute("data-phase") === "failed");
    expect(cards()).toHaveLength(MAX_VISIBLE);
    expect(within(region()).getByText("2 more print notifications")).toBeVisible();
    fireEvent.click(within(cards()[0]!).getByRole("button", { name: "Dismiss notification" }));
    expect(cards()).toHaveLength(MAX_VISIBLE);
    expect(within(region()).getByText("1 more print notification")).toBeVisible();
  });

  it("retries every failed job of a batch and follows the new jobs", async () => {
    const calls2 = mockApi({
      "GET /api/v1/printers": [PRINTER_A],
      [`GET /api/v1/jobs/${A}`]: job(A, PRINTER_A.id, "failed"),
      [`POST /api/v1/jobs/${A}/retry`]: job(NEW, PRINTER_A.id, "queued"),
      [`POST /api/v1/jobs/${B}/retry`]: job("aaaaaaaa-0000-4000-8000-00000000000b", PRINTER_A.id, "queued"),
    }).calls;
    watch("cart", [A, B]);
    event(A, "failed", { error_code: "ipp_busy" });
    event(B, "failed", { error_code: "ipp_busy" });
    fireEvent.click(await within(region()).findByRole("button", { name: "Retry" }));
    await waitFor(() => expect(calls2.filter((c) => c.path.endsWith("/retry")).map((c) => c.path)).toEqual([`/api/v1/jobs/${A}/retry`, `/api/v1/jobs/${B}/retry`]));
    expect(await within(region()).findByText(/Queued/)).toBeVisible();
  });
});

describe("a tape batch in parts (#277)", () => {
  const BATCH = "bbbbbbbb-0000-4000-8000-000000000001";
  const label = (i: number) => `cccccccc-0000-4000-8000-${String(i).padStart(12, "0")}`;
  const labels = (n: number, from = 1) => Array.from({ length: n }, (_, i) => label(from + i));
  const watchRun = (jobIds: string[], starts: number[]) =>
    act(() => void watchPrint({ kind: "cart", printerId: PRINTER_A.id, jobIds, run: { batchId: BATCH, subJobStarts: starts, confirmed: [] } }));

  it("shows the part that prints, waits after it, and Continue starts the next part", async () => {
    const run = { state: "printing", current_sub_job: 2, sub_jobs: 2, sub_job_size: 3, sub_job_starts: [0, 3], job_ids: labels(5), confirmed_job_ids: [], unknown_from: null, unknown_to: null, stop_code: null };
    const { calls: runCalls } = mockApi({ "GET /api/v1/printers": [PRINTER_A], [`POST /api/v1/batches/${BATCH}/continue`]: run });
    const jobs = labels(5);
    watchRun(jobs, [0, 3]);
    event(jobs[0]!, "printing");
    expect(await within(region()).findByText(/Part 1 of 2/)).toBeVisible();
    jobs.slice(0, 3).forEach((j) => event(j, "completed"));
    expect(await within(region()).findByText(/Part 1 of 2 is done/)).toBeVisible();
    fireEvent.click(within(region()).getByRole("button", { name: "Continue with part 2" }));
    await waitFor(() => expect(runCalls.some((c) => c.method === "POST" && c.path === `/api/v1/batches/${BATCH}/continue`)).toBe(true));
    await waitFor(() => expect(within(region()).queryByRole("button", { name: "Continue with part 2" })).toBeNull());
    expect(within(region()).getByText(/Part 2 of 2/)).toBeVisible();
  });

  it("after a stop names the labels to count and reprints from the one the user picks", async () => {
    const jobs = labels(25);
    const fresh = labels(11, 100);
    const reprint = { new_job_ids: fresh, confirmed_job_ids: jobs.slice(10, 14), job_ids: [...jobs.slice(0, 14), ...fresh], run: { state: "printing", current_sub_job: 2, sub_jobs: 2, sub_job_size: 50, sub_job_starts: [0, 14], job_ids: [...jobs.slice(0, 14), ...fresh], confirmed_job_ids: jobs.slice(10, 14), unknown_from: null, unknown_to: null, stop_code: null } };
    const { calls: runCalls } = mockApi({ "GET /api/v1/printers": [PRINTER_A], [`POST /api/v1/batches/${BATCH}/reprint`]: reprint });
    watchRun(jobs, [0]);
    jobs.slice(0, 10).forEach((j) => event(j, "completed"));
    jobs.slice(10, 20).forEach((j) => event(j, "failed", { error_code: "outcome_unknown" }));
    jobs.slice(20).forEach((j) => event(j, "failed", { error_code: "not_started" }));
    const card = region();
    expect(await within(card).findByText(/Labels 11 to 20 may or may not have printed/)).toBeVisible();
    expect(within(card).queryByRole("button", { name: "Retry" })).toBeNull();
    fireEvent.change(within(card).getByRole("combobox", { name: "First missing label" }), { target: { value: "15" } });
    fireEvent.click(within(card).getByRole("button", { name: "Reprint from label 15" }));
    await waitFor(() => expect(runCalls.find((c) => c.path === `/api/v1/batches/${BATCH}/reprint`)?.body).toBe(JSON.stringify({ from_label: 15 })));
    // The card follows the new jobs: the stop is gone, 14 labels count as printed.
    await waitFor(() => expect(within(card).queryByText(/may or may not have printed/)).toBeNull());
    expect(within(card).getByText(/14 of 25 items/)).toBeVisible();
  });

  it("a group the printer refused before sending is not an unknown outcome: it offers to print from its first label", async () => {
    const jobs = labels(25);
    const { calls: runCalls } = mockApi({
      "GET /api/v1/printers": [PRINTER_A],
      [`POST /api/v1/batches/${BATCH}/reprint`]: { new_job_ids: [], confirmed_job_ids: [], job_ids: jobs.slice(0, 10), skipped_job_ids: [], run: null },
    });
    watchRun(jobs, [0]);
    jobs.slice(0, 10).forEach((j) => event(j, "completed"));
    jobs.slice(10, 20).forEach((j) => event(j, "failed", { error_code: "tape_mismatch" }));
    jobs.slice(20).forEach((j) => event(j, "failed", { error_code: "not_started" }));
    const card = region();
    expect(await within(card).findByText(/Nothing from label 11 on was sent/)).toBeVisible();
    expect(within(card).getByText(/does not match the label/)).toBeVisible();
    expect(within(card).queryByText(/may or may not have printed/)).toBeNull();
    expect(within(card).queryByRole("combobox")).toBeNull();
    fireEvent.click(within(card).getByRole("button", { name: "Print labels 11 to 25 again" }));
    await waitFor(() => expect(runCalls.find((c) => c.path === `/api/v1/batches/${BATCH}/reprint`)?.body).toBe(JSON.stringify({ from_label: 11 })));
  });

  it("Discard gives the waiting part up and closes the card", async () => {
    const { calls: runCalls } = mockApi({ "GET /api/v1/printers": [PRINTER_A], [`POST /api/v1/batches/${BATCH}/discard`]: null });
    const jobs = labels(5);
    watchRun(jobs, [0, 3]);
    jobs.slice(0, 3).forEach((j) => event(j, "completed"));
    fireEvent.click(await within(region()).findByRole("button", { name: "Discard the rest" }));
    await waitFor(() => expect(runCalls.some((c) => c.method === "POST" && c.path === `/api/v1/batches/${BATCH}/discard`)).toBe(true));
    await waitFor(() => expect(within(region()).queryByText(/Part 1 of 2 is done/)).toBeNull());
  });
});
