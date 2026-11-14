// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { configure, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { renderApp } from "../../test-utils";
import { mockApi, pngResponse, PRINTER_A, PRINTER_B, respond, status, type Call } from "../test-api";
import { reloadCart } from "./cart";

const BATCH = "cccccccc-0000-4000-8000-000000000001";
const JOB = "jjjjjjjj-0000-4000-8000-000000000001";
const QL = (layout_defaults: Record<string, unknown> = {}) => ({ ...PRINTER_B, paused: false, layout_defaults });
const wide = (id: string) => status(id, { tape_loaded: "62mm", tape_width_mm: 62 });

// Most tests go straight from renderApp to the first "Label preview". That one findBy covers the
// whole chain: app boot, the lookup, the printers and their status, the 200 ms preview debounce
// (PREVIEW_DEBOUNCE_MS) and the preview request. Measured from the end of renderApp: 0.5-1.3 s
// alone, 0.9-1.1 s under `vitest --coverage` (about 2.5 times slower), so the default 1 s window
// expired in the 1.5.0 gate. The window is widened for this file only and restored afterwards;
// the assertions are unchanged.
let defaultAsyncTimeout = 1000;
beforeAll(() => {
  configure((current) => {
    defaultAsyncTimeout = current.asyncUtilTimeout;
    return { asyncUtilTimeout: 5000 };
  });
});
afterAll(() => configure({ asyncUtilTimeout: defaultAsyncTimeout }));

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem("lph.printer", PRINTER_B.id);
  reloadCart();
});
afterEach(() => vi.unstubAllGlobals());

function routes(over: { printer?: unknown; status?: unknown; preview?: () => Response } = {}) {
  return {
    "GET /api/v1/lookup/snipeit/42": { app: "snipeit", id: "42", name: "Cordless drill", url: "https://assets.example.invalid/42", extra: {} },
    "GET /api/v1/printers": [PRINTER_A, over.printer ?? QL()],
    [`GET /api/v1/printers/${PRINTER_A.id}/status`]: status(PRINTER_A.id),
    [`GET /api/v1/printers/${PRINTER_B.id}/status`]: over.status ?? wide(PRINTER_B.id),
    "POST /api/v1/render/preview": over.preview ?? (() => pngResponse()),
    [`POST /api/v1/print/${PRINTER_B.id}/batch`]: { batch_id: BATCH, printer_id: PRINTER_B.id, queued_at: "x", job_ids: [JOB] },
  };
}

const previews = (calls: Call[]) => calls.filter((c) => c.path === "/api/v1/render/preview").map((c) => JSON.parse(c.body!) as Record<string, unknown>);
const lastPreview = (calls: Call[]) => previews(calls).at(-1)!;

describe("the QL 62 mm layout choice in the print panel", () => {
  it("preselects the printer's stored default and previews exactly that", async () => {
    const { calls } = mockApi(routes({ printer: QL({ "62": { orientation: "across", preset: "small_qr" } }) }));
    await renderApp({ path: "/asset/42" });
    expect(await screen.findByRole("radio", { name: "Small QR" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "Across" })).toBeChecked();
    await screen.findByRole("img", { name: "Label preview" });
    expect(lastPreview(calls)).toMatchObject({ tape_mm: 62, orientation: "across", layout_preset: "small_qr" });
  });

  it("falls back to across and compact when nothing is stored", async () => {
    const { calls } = mockApi(routes());
    await renderApp({ path: "/asset/42" });
    expect(await screen.findByRole("radio", { name: "Compact" })).toBeChecked();
    await screen.findByRole("img", { name: "Label preview" });
    expect(lastPreview(calls)).toMatchObject({ orientation: "across", layout_preset: "compact" });
  });

  it("a stored along default selects along and hides the arrangement", async () => {
    mockApi(routes({ printer: QL({ "62": { orientation: "along", preset: null } }) }));
    await renderApp({ path: "/asset/42" });
    expect(await screen.findByRole("radio", { name: "Along" })).toBeChecked();
    expect(screen.queryByRole("radiogroup", { name: "Arrangement" })).toBeNull();
  });

  it("a new arrangement asks for a new preview and travels with the job", async () => {
    const { calls } = mockApi(routes());
    await renderApp({ path: "/asset/42" });
    await screen.findByRole("img", { name: "Label preview" });
    await userEvent.click(screen.getByRole("radio", { name: "Standard" }));
    await vi.waitFor(() => expect(lastPreview(calls)).toMatchObject({ orientation: "across", layout_preset: "standard" }));
    await userEvent.click(screen.getByRole("button", { name: "Print now" }));
    expect(await screen.findByText(/Sent to Office QL-820NWB/)).toBeVisible();
    const post = calls.find((c) => c.path === `/api/v1/print/${PRINTER_B.id}/batch`)!;
    expect(JSON.parse(post.body!)).toEqual({
      items: [
        {
          content_type: "qr_two_lines",
          options: { copies: 1, orientation: "across", layout_preset: "standard" },
          lookup: { app: "snipeit", identifier: "42" },
        },
      ],
    });
  });

  it("along previews and prints without a preset", async () => {
    const { calls } = mockApi(routes());
    await renderApp({ path: "/asset/42" });
    await screen.findByRole("img", { name: "Label preview" });
    await userEvent.click(screen.getByRole("radio", { name: "Along" }));
    await vi.waitFor(() => expect(lastPreview(calls)).toMatchObject({ orientation: "along" }));
    expect(lastPreview(calls)).not.toHaveProperty("layout_preset");
    await userEvent.click(screen.getByRole("button", { name: "Print now" }));
    await screen.findByText(/Sent to Office QL-820NWB/);
    const post = calls.find((c) => c.path === `/api/v1/print/${PRINTER_B.id}/batch`)!;
    expect(JSON.parse(post.body!).items[0].options).toEqual({ copies: 1, orientation: "along" });
  });

  it("debounces: a quick run of changes asks for one preview, not one per click", async () => {
    const { calls } = mockApi(routes());
    await renderApp({ path: "/asset/42" });
    await screen.findByRole("img", { name: "Label preview" });
    const before = previews(calls).length;
    await userEvent.click(screen.getByRole("radio", { name: "Standard" }));
    await userEvent.click(screen.getByRole("radio", { name: "Small QR" }));
    await userEvent.click(screen.getByRole("radio", { name: "Standard" }));
    await vi.waitFor(() => expect(previews(calls).length).toBeGreaterThan(before));
    await new Promise((resolve) => setTimeout(resolve, 400));
    expect(previews(calls).length - before).toBe(1);
  });

  it("a QR code that is too long names the limit", async () => {
    mockApi(
      routes({
        preview: () =>
          respond(422, { error_code: "qr_payload_too_long", error_message: "x", error_detail: { length: 144, max_bytes: 122 } }),
      }),
    );
    await renderApp({ path: "/asset/42" });
    expect(await screen.findByRole("alert")).toHaveTextContent("144");
    expect(screen.getByRole("alert")).toHaveTextContent("122");
    expect(screen.getByRole("button", { name: "Print now" })).toBeEnabled();
  });

  it("explains that across is for 62 mm tape only", async () => {
    mockApi(routes({ preview: () => respond(409, { error_code: "unsupported_tape", error_message: "x" }) }));
    await renderApp({ path: "/asset/42" });
    expect(await screen.findByRole("alert")).toHaveTextContent(/62 mm/);
  });

  it("offers no choice on a narrower tape", async () => {
    const { calls } = mockApi(routes({ status: status(PRINTER_B.id, { tape_loaded: "12mm", tape_width_mm: 12 }) }));
    await renderApp({ path: "/asset/42" });
    await screen.findByRole("img", { name: "Label preview" });
    expect(screen.queryByRole("radiogroup", { name: "Direction" })).toBeNull();
    expect(lastPreview(calls)).not.toHaveProperty("orientation");
  });

  it("offers no choice on a P-touch printer", async () => {
    localStorage.setItem("lph.printer", PRINTER_A.id);
    const { calls } = mockApi({ ...routes(), [`GET /api/v1/printers/${PRINTER_A.id}/status`]: wide(PRINTER_A.id) });
    await renderApp({ path: "/asset/42" });
    await screen.findByRole("img", { name: "Label preview" });
    expect(screen.queryByRole("radiogroup", { name: "Direction" })).toBeNull();
    expect(lastPreview(calls)).not.toHaveProperty("orientation");
  });
});
