// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { I18nProvider } from "@lingui/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { i18n, initI18n } from "../../../i18n";
import type * as PrintWatch from "../../jobs/printWatch";
import type { JobLive } from "../../jobs/printWatch";
import { mockApi, PAGE_CAPABILITIES, PAGE_PRINTER, respond, sheetRead, type Call } from "../../test-api";
import { ActivateBackSide, type BackSideTarget } from "./ActivateBackSide";

const live: { value: Record<string, JobLive> } = { value: {} };
const listeners = new Set<() => void>();
vi.mock("../../jobs/printWatch", async (original) => {
  const real = await original<typeof PrintWatch>();
  const { useSyncExternalStore } = await import("react");
  return {
    ...real,
    watchPrint: vi.fn(() => "w1"),
    claimJob: vi.fn(() => () => undefined),
    useJobLive: (id: string | null | undefined) =>
      useSyncExternalStore(
        (fn) => {
          listeners.add(fn);
          return () => listeners.delete(fn);
        },
        () => (id ? live.value[id] : undefined),
      ),
  };
});

const setLive = (id: string, phase: JobLive["phase"], errorCode: string | null = null) =>
  act(() => {
    live.value = { ...live.value, [id]: { phase, atPrinter: null, atPrinterReasons: [], errorCode } };
    listeners.forEach((fn) => fn());
  });

const P = PAGE_PRINTER.id;
const JOB = "eeeeeeee-0000-4000-8000-000000000001";
const JOB2 = "eeeeeeee-0000-4000-8000-000000000002";
const DOWN = { print_side: "down", leading_edge: "bottom" } as const;
const caps = (loading: unknown) => ({ ...PAGE_CAPABILITIES, trays: PAGE_CAPABILITIES.trays!.map((t) => (t.is_default ? { ...t, loading } : t)) });
const NEW: BackSideTarget = { kind: "new", body: { type: "avery-zweckform-3490", used_cells: [] } };

function routes(over: Record<string, unknown> = {}) {
  return {
    "GET /api/v1/printers": [PAGE_PRINTER],
    [`GET /api/v1/printers/${P}/capabilities`]: caps(DOWN),
    "POST /api/v1/sheets": { ...sheetRead("A3490-0001"), id_placement: "back_side", job_id: JOB },
    "POST /api/v1/sheets/A3490-0001/back-side": { job_id: JOB2 },
    "POST /api/v1/sheets/A3490-0001/back-side/confirm": { ...sheetRead("A3490-0001"), id_placement: "back_side", id_printed: true },
    [`GET /api/v1/jobs/${JOB}`]: { id: JOB, state: "queued", error: null },
    [`GET /api/v1/jobs/${JOB2}`]: { id: JOB2, state: "queued", error: null },
    ...over,
  };
}

function show(target: BackSideTarget = NEW, props: { onUseCell?: () => void; onClose?: () => void } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const onClose = props.onClose ?? vi.fn();
  render(
    <QueryClientProvider client={client}>
      <I18nProvider i18n={i18n}>
        <ActivateBackSide
          target={target}
          codeLabel="A3490-0001"
          typeLabel="Avery Zweckform 3490"
          page={{ w: 210, h: 297 }}
          strips={[{ x_mm: 33.5, y_mm: 22, w_mm: 22, h_mm: 253 }]}
          initialPrinterId={P}
          onUseCell={props.onUseCell}
          onClose={onClose}
        />
      </I18nProvider>
    </QueryClientProvider>,
  );
  return { onClose };
}

const posts = (calls: Call[], path: string) => calls.filter((c) => c.method === "POST" && c.path === path);
const current = () => screen.getByRole("listitem", { current: "step" });

beforeEach(async () => {
  live.value = {};
  await initI18n("en");
});
afterEach(() => vi.unstubAllGlobals());

describe("activating a sheet with its code on the back", () => {
  it("the stepper starts at Turn over with the sheet code from the next-code hint", async () => {
    mockApi(routes());
    show();
    expect(current()).toHaveTextContent("Turn over");
    expect(screen.getByText("A3490-0001")).toBeVisible();
  });

  it("the instruction follows the tray's loading", async () => {
    mockApi(routes());
    show();
    expect(await screen.findByText("Load it into Main tray, liner side down")).toBeVisible();
    expect(screen.getByText("Set for this tray in the printer settings.")).toBeVisible();
  });

  it("an unset tray asks the loading question first", async () => {
    mockApi(routes({ [`GET /api/v1/printers/${P}/capabilities`]: caps(null) }));
    show();
    expect(await screen.findByRole("heading", { name: "How does this tray take paper?" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Print sheet code" })).toBeDisabled();
  });

  it("Print sheet code creates the sheet with back_side and goes to Print", async () => {
    const { calls } = mockApi(routes());
    show();
    await screen.findByText("Load it into Main tray, liner side down");
    await userEvent.click(screen.getByRole("button", { name: "Print sheet code" }));
    await waitFor(() => expect(posts(calls, "/api/v1/sheets")).toHaveLength(1));
    expect(JSON.parse(posts(calls, "/api/v1/sheets")[0]!.body!)).toEqual({
      type: "avery-zweckform-3490",
      used_cells: [],
      id_placement: "back_side",
      printer: P,
      tray: "main",
    });
    await waitFor(() => expect(current()).toHaveTextContent("Print"));
  });

  it("a finished job moves to Confirm, a failed job shows the error text and Print again", async () => {
    const { calls } = mockApi(routes());
    show();
    await screen.findByText("Load it into Main tray, liner side down");
    await userEvent.click(screen.getByRole("button", { name: "Print sheet code" }));
    await waitFor(() => expect(current()).toHaveTextContent("Print"));
    setLive(JOB, "failed", "printer_cover_open");
    expect(await screen.findByText("The printer cover is open. Close it and retry.")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Print again" }));
    await waitFor(() => expect(posts(calls, "/api/v1/sheets/A3490-0001/back-side")).toHaveLength(1));
    setLive(JOB2, "done");
    expect(await screen.findByRole("heading", { name: "Did it print?" })).toBeVisible();
    expect(current()).toHaveTextContent("Confirm");
  });

  it("Yes, it is printed calls confirm and closes", async () => {
    const { calls } = mockApi(routes());
    const { onClose } = show({ kind: "existing", code: "A3490-0001" });
    await screen.findByText("Load it into Main tray, liner side down");
    await userEvent.click(screen.getByRole("button", { name: "Print sheet code" }));
    await waitFor(() => expect(posts(calls, "/api/v1/sheets/A3490-0001/back-side")).toHaveLength(1));
    setLive(JOB2, "done");
    await userEvent.click(await screen.findByRole("button", { name: "Yes, it is printed" }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(posts(calls, "/api/v1/sheets/A3490-0001/back-side/confirm")).toHaveLength(1);
  });

  it("Print again queues a new job for the same sheet", async () => {
    const { calls } = mockApi(routes());
    show({ kind: "existing", code: "A3490-0001" });
    await screen.findByText("Load it into Main tray, liner side down");
    await userEvent.click(screen.getByRole("button", { name: "Print sheet code" }));
    await waitFor(() => expect(posts(calls, "/api/v1/sheets/A3490-0001/back-side")).toHaveLength(1));
    setLive(JOB2, "done");
    await userEvent.click(await screen.findByRole("button", { name: "Print again" }));
    await waitFor(() => expect(posts(calls, "/api/v1/sheets/A3490-0001/back-side")).toHaveLength(2));
    expect(posts(calls, "/api/v1/sheets")).toHaveLength(0);
  });

  it("a create that fails after the commit adopts the sheet code: the next press prints that sheet (I1)", async () => {
    const { calls } = mockApi(
      routes({
        "POST /api/v1/sheets": () =>
          respond(409, { error_code: "printer-unavailable", error_message: "Busy.", error_detail: { sheet_code: "A3490-0007" } }),
        "POST /api/v1/sheets/A3490-0007/back-side": { job_id: JOB2 },
      }),
    );
    show();
    await screen.findByText("Load it into Main tray, liner side down");
    await userEvent.click(screen.getByRole("button", { name: "Print sheet code" }));
    await waitFor(() => expect(posts(calls, "/api/v1/sheets")).toHaveLength(1));
    expect(await screen.findByText("A3490-0007")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Print sheet code" }));
    await waitFor(() => expect(posts(calls, "/api/v1/sheets/A3490-0007/back-side")).toHaveLength(1));
    expect(posts(calls, "/api/v1/sheets")).toHaveLength(1);
  });

  it("starts watching the job once (M6)", async () => {
    const { watchPrint } = await import("../../jobs/printWatch");
    vi.mocked(watchPrint).mockClear();
    mockApi(routes());
    show({ kind: "existing", code: "A3490-0001" });
    await screen.findByText("Load it into Main tray, liner side down");
    await userEvent.click(screen.getByRole("button", { name: "Print sheet code" }));
    await waitFor(() => expect(current()).toHaveTextContent("Print"));
    expect(vi.mocked(watchPrint)).toHaveBeenCalledTimes(1);
  });

  it("survives a scrollIntoView that returns a Promise, as newer browsers do", async () => {
    // React calls an effect's return value as its cleanup; a Promise there crashed the dialog on the step change.
    const original = Element.prototype.scrollIntoView;
    Element.prototype.scrollIntoView = vi.fn(() => Promise.resolve()) as unknown as typeof original;
    try {
      mockApi(routes());
      show({ kind: "existing", code: "A3490-0001" });
      await screen.findByText("Load it into Main tray, liner side down");
      await userEvent.click(screen.getByRole("button", { name: "Print sheet code" }));
      await waitFor(() => expect(current()).toHaveTextContent("Print"));
      setLive(JOB2, "done");
      expect(await screen.findByRole("heading", { name: "Did it print?" })).toBeVisible();
    } finally {
      Element.prototype.scrollIntoView = original;
    }
  });

  it("Use a reserved cell instead switches the dialog to the reserved cell option", async () => {
    mockApi(routes());
    const onUseCell = vi.fn();
    show(NEW, { onUseCell });
    await userEvent.click(screen.getByRole("button", { name: "Use a reserved cell instead" }));
    expect(onUseCell).toHaveBeenCalled();
  });

  it("Escape before printing creates nothing", async () => {
    const { calls } = mockApi(routes());
    const { onClose } = show();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onClose).toHaveBeenCalled();
    expect(posts(calls, "/api/v1/sheets")).toHaveLength(0);
  });
});
