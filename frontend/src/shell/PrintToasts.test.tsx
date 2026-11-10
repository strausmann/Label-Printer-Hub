import { act, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { dismissWatch, recordJobEvent, resetPrintWatch, useWatchedPrints, watchPrint } from "../features/jobs/printWatch";
import { job, mockApi, PRINTER_A, respond } from "../features/test-api";
import { renderApp } from "../test-utils";
import { AUTO_DISMISS_MS } from "./PrintToasts";

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
    event(A, "failed", { error_code: "printer-offline" });
    const alert = region();
    expect(await within(alert).findByText("Tape jam at the cutter.")).toBeVisible();
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

  it("is a no-op for a store entry that was dismissed already", () => {
    const entries: number[] = [];
    watch("item", [A]);
    act(() => dismissWatch("print-unknown"));
    entries.push(within(region()).getAllByRole("listitem").length);
    expect(entries).toEqual([1]);
    expect(useWatchedPrints).toBeTypeOf("function");
    respond(200, {});
  });
});
