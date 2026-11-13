import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { recordJobEvent, resetPrintWatch } from "../jobs/printWatch";
import { apiErrorBody, job, respond } from "../test-api";
import { BASE, button, JOB, open, P, resetBetweenTests, RETRY } from "./CalibrationPage.kit";

vi.setConfig({ testTimeout: 15_000 });
resetBetweenTests();

describe("the live print status line (#239)", () => {
  const event = (to: string, extra: Record<string, unknown> = {}) =>
    act(() => recordJobEvent({ job_id: JOB, from_state: "queued", to_state: to, queue_depth: 1, error_code: null, ...extra }));
  const lineOf = (name: string) => screen.getByRole("status", { name });
  const printed = async (routesExtra: Record<string, unknown> = {}) => {
    const api = await open({ [`POST ${BASE}/main/page`]: respond(202, { job_id: JOB }), ...routesExtra });
    await userEvent.click(await button("Print calibration page"));
    await within(lineOf("Calibration page status")).findByText("Queued");
    return api;
  };
  // The status element holds only the sentence; the link and Retry sit beside it, in the same line block.
  const around = (line: HTMLElement) => within(line.parentElement!);
  // A real calibration page job, as the hub stores it.
  const PAGE_JOB = { template_key: null, payload: { kind: "calibration_page", tray: "main", detail: { type_key: "L4736REV", version: 1 } } };
  const stack = () => within(screen.getByRole("region", { name: "Print status" }));
  beforeEach(() => resetPrintWatch());

  it("result does not sit in the button row", async () => {
    await printed();
    const line = lineOf("Calibration page status");
    const row = screen.getByRole("link", { name: "Download PDF" }).parentElement!;
    expect(row.contains(line)).toBe(false);
    expect(row.contains(screen.getByRole("link", { name: "Show the job" }))).toBe(false);
    // Below the row, in document order, and in the same step section.
    expect(row.compareDocumentPosition(line) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(row.closest("section")!.contains(line)).toBe(true);
  });

  it("the line is there before the first print, empty, so nothing is added to the page later", async () => {
    await open();
    const line = await screen.findByRole("status", { name: "Calibration page status" });
    expect(line).toHaveAttribute("aria-live", "polite");
    expect(line.textContent).toBe("");
  });

  it("status follows job events queued -> printing -> done", async () => {
    await printed();
    const line = lineOf("Calibration page status");
    expect(around(line).getByRole("link", { name: "Show the job" })).toHaveAttribute("href", `/jobs/${JOB}`);
    event("printing");
    expect(within(line).getByText("Printing")).toBeVisible();
    event("printing", { at_printer: "stopped" });
    expect(within(line).getByText("Stopped at the printer")).toBeVisible();
    event("completed");
    expect(within(line).getByText("Done")).toBeVisible();
    expect(within(line).getByText(/measure the crossings/)).toBeVisible();
    // The stack agrees with the line: both read the same job state.
    expect(within(screen.getByRole("region", { name: "Print status" })).getByText("Done")).toBeVisible();
  });

  it("failed shows the localised error and a Retry that the line follows", async () => {
    const { calls } = await printed({
      [`GET /api/v1/jobs/${JOB}`]: job(JOB, P, "failed", { ...PAGE_JOB, error: "printer_offline: down" }),
      [`POST /api/v1/jobs/${JOB}/retry`]: job(RETRY, P, "queued", PAGE_JOB),
    });
    event("failed", { error_code: "printer_offline" });
    const line = lineOf("Calibration page status");
    expect(within(line).getByText("Failed")).toBeVisible();
    expect(within(line).getByText(/The printer could not be reached/)).toBeVisible();
    fireEvent.click(await around(line).findByRole("button", { name: "Retry" }));
    await waitFor(() => expect(within(line).getByText("Queued")).toBeVisible());
    expect(calls.some((c) => c.method === "POST" && c.path === `/api/v1/jobs/${JOB}/retry`)).toBe(true);
    expect(around(line).getByRole("link", { name: "Show the job" })).toHaveAttribute("href", `/jobs/${RETRY}`);
    act(() => recordJobEvent({ job_id: RETRY, from_state: "queued", to_state: "completed", queue_depth: 0, error_code: null }));
    expect(within(line).getByText("Done")).toBeVisible();
  });

  it("Retry follows the hub's job record, not the event: a record that does not say failed yet offers none", async () => {
    // A real calibration page job is retryable once it failed; here the record still says "done" while the event
    // already said "failed" (the two disagree for a moment), and the hub's record decides.
    const { calls } = await printed({ [`GET /api/v1/jobs/${JOB}`]: job(JOB, P, "done", PAGE_JOB) });
    event("failed", { error_code: "interrupted" });
    const line = lineOf("Calibration page status");
    expect(await within(line).findByText(/interrupted while it was printing/)).toBeVisible();
    await waitFor(() => expect(calls.some((c) => c.path === `/api/v1/jobs/${JOB}`)).toBe(true));
    expect(around(line).queryByRole("button", { name: "Retry" })).toBeNull();
  });

  it("a refused retry says why, in words", async () => {
    await printed({
      [`GET /api/v1/jobs/${JOB}`]: job(JOB, P, "failed", { ...PAGE_JOB, error: "ipp_aborted: x" }),
      [`POST /api/v1/jobs/${JOB}/retry`]: respond(409, apiErrorBody("printer_disabled", "off")),
    });
    event("failed", { error_code: "ipp_aborted" });
    const line = lineOf("Calibration page status");
    fireEvent.click(await around(line).findByRole("button", { name: "Retry" }));
    expect(await around(line).findByText("The printer is switched off. Switch it on in the settings, then retry.")).toBeVisible();
  });

  it("announces once: the line is live, the stack shows the card without a live region of its own", async () => {
    await printed({ [`GET /api/v1/jobs/${JOB}`]: job(JOB, P, "failed", { ...PAGE_JOB, error: "ipp_aborted: x" }) });
    // The card is there from the first moment, and in no live region (the line announces it).
    expect(stack().getByText("Queued").closest("[aria-live]")).toBeNull();
    event("failed", { error_code: "ipp_aborted" });
    const line = lineOf("Calibration page status");
    expect(stack().getByText("Failed").closest("[aria-live]")).toBeNull();
    expect(line).toHaveAttribute("aria-live", "polite");
    // The live element holds only the sentence: the controls are beside it, so a state change does not re-read them.
    expect(within(line).queryByRole("link")).toBeNull();
    expect(within(line).queryByRole("button")).toBeNull();
    expect(await around(line).findByRole("button", { name: "Retry" })).toBeVisible();
  });

  it("the stack announces the card again once the page line is gone", async () => {
    await printed({ [`GET /api/v1/jobs/${JOB}`]: job(JOB, P, "failed", { ...PAGE_JOB, error: "ipp_aborted: x" }) });
    event("failed", { error_code: "ipp_aborted" });
    expect(stack().getByText("Failed").closest("[aria-live]")).toBeNull();
    await userEvent.click(screen.getAllByRole("link", { name: "Jobs" })[0]!);
    await waitFor(() => expect(stack().getByText("Failed").closest("[aria-live]")?.getAttribute("aria-live")).toBe("assertive"));
  });

  it("Retry pressed in the line and in the stack before the first answer clones the job once", async () => {
    let answer: (() => void) | undefined;
    const { calls } = await printed({
      [`GET /api/v1/jobs/${JOB}`]: job(JOB, P, "failed", { ...PAGE_JOB, error: "ipp_aborted: x" }),
      [`POST /api/v1/jobs/${JOB}/retry`]: () => new Promise((resolve) => (answer = () => resolve(job(RETRY, P, "queued", PAGE_JOB)))),
    });
    event("failed", { error_code: "ipp_aborted" });
    const line = lineOf("Calibration page status");
    fireEvent.click(await around(line).findByRole("button", { name: "Retry" }));
    fireEvent.click(await stack().findByRole("button", { name: "Retry" }));
    await waitFor(() => expect(calls.filter((c) => c.method === "POST" && c.path.endsWith("/retry"))).toHaveLength(1));
    act(() => answer?.());
    await waitFor(() => expect(within(line).getByText("Queued")).toBeVisible());
    expect(around(line).getByRole("link", { name: "Show the job" })).toHaveAttribute("href", `/jobs/${RETRY}`);
    expect(calls.filter((c) => c.method === "POST" && c.path.endsWith("/retry"))).toHaveLength(1);
    // One card, following the new job.
    expect(stack().getAllByText("Queued")).toHaveLength(1);
  });

  it("leaving the page before the POST answers does not leave the card unannounced", async () => {
    let answer: (() => void) | undefined;
    await open({
      [`POST ${BASE}/main/page`]: () => new Promise((resolve) => (answer = () => resolve(respond(202, { job_id: JOB })))),
      [`GET /api/v1/jobs/${JOB}`]: job(JOB, P, "failed", { ...PAGE_JOB, error: "ipp_aborted: x" }),
    });
    await userEvent.click(await button("Print calibration page"));
    await waitFor(() => expect(answer).toBeDefined());
    // Away from the calibration page: the line is gone before the hub answered.
    await userEvent.click(screen.getAllByRole("link", { name: "Jobs" })[0]!);
    await screen.findByRole("heading", { level: 1, name: "Jobs" });
    await act(async () => answer?.());
    expect(await stack().findByText("Queued")).toBeVisible();
    // Nobody claimed it: it is in a live region, and a later failure is announced assertively.
    expect(stack().getByText("Queued").closest("[aria-live]")?.getAttribute("aria-live")).toBe("polite");
    event("failed", { error_code: "ipp_aborted" });
    expect(stack().getByText("Failed").closest("[aria-live]")?.getAttribute("aria-live")).toBe("assertive");
  });

  it("after a Retry pressed in the stack the new job's card is still in the quiet list", async () => {
    // The window itself (claim handed over, no moment unclaimed) is pinned by the printWatch unit test
    // "a retry hands the claim over"; here the end state through the real components.
    await printed({
      [`GET /api/v1/jobs/${JOB}`]: job(JOB, P, "failed", { ...PAGE_JOB, error: "ipp_aborted: x" }),
      [`POST /api/v1/jobs/${JOB}/retry`]: job(RETRY, P, "queued", PAGE_JOB),
    });
    event("failed", { error_code: "ipp_aborted" });
    const line = lineOf("Calibration page status");
    fireEvent.click(await stack().findByRole("button", { name: "Retry" }));
    await waitFor(() => expect(around(line).getByRole("link", { name: "Show the job" })).toHaveAttribute("href", `/jobs/${RETRY}`));
    expect(stack().getByText("Queued").closest("[aria-live]")).toBeNull();
    act(() => recordJobEvent({ job_id: RETRY, from_state: "queued", to_state: "failed", queue_depth: 0, error_code: "ipp_aborted" }));
    expect(stack().getByText("Failed").closest("[aria-live]")).toBeNull();
  });

  it("a Retry pressed in the stack moves the line to the new job", async () => {
    const { calls } = await printed({
      [`GET /api/v1/jobs/${JOB}`]: job(JOB, P, "failed", { ...PAGE_JOB, error: "ipp_aborted: x" }),
      [`POST /api/v1/jobs/${JOB}/retry`]: job(RETRY, P, "queued", PAGE_JOB),
    });
    event("failed", { error_code: "ipp_aborted" });
    const line = lineOf("Calibration page status");
    fireEvent.click(await stack().findByRole("button", { name: "Retry" }));
    await waitFor(() => expect(within(line).getByText("Queued")).toBeVisible());
    expect(around(line).getByRole("link", { name: "Show the job" })).toHaveAttribute("href", `/jobs/${RETRY}`);
    expect(calls.filter((c) => c.method === "POST" && c.path.endsWith("/retry"))).toHaveLength(1);
    act(() => recordJobEvent({ job_id: RETRY, from_state: "queued", to_state: "completed", queue_depth: 0, error_code: null }));
    expect(within(line).getByText("Done")).toBeVisible();
  });

  it("the check page has its own line under its own button", async () => {
    await open({ [`POST ${BASE}/main/page`]: respond(202, { job_id: JOB }) });
    await userEvent.click(await button("Check print with correction"));
    const line = await screen.findByRole("status", { name: "Check page status" });
    await within(line).findByText("Queued");
    event("completed");
    expect(within(line).getByText(/within 0\.5 mm/)).toBeVisible();
    expect(lineOf("Calibration page status").textContent).toBe("");
    const row = screen.getByRole("button", { name: "Check print with correction" }).parentElement!;
    expect(row.contains(line)).toBe(false);
  });

  it("a refusal because the printer is held after a device swap stays in the page", async () => {
    await open({
      [`POST ${BASE}/main/page`]: () =>
        respond(409, { detail: { type: "printer-identity-mismatch", title: "Held", status: 409, detail: "held" } }),
    });
    await userEvent.click(await button("Print calibration page"));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("This printer may be a different device now.");
    const row = screen.getByRole("link", { name: "Download PDF" }).parentElement!;
    expect(row.contains(alert)).toBe(false);
  });
});
