import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderApp } from "../../test-utils";
import { mockApi, pngResponse, PRINTER_A, PRINTER_B, status } from "../test-api";
import { CART_KEY, reloadCart } from "./cart";

const BATCH = "cccccccc-0000-4000-8000-000000000001";
const items = [
  { app: "snipeit", id: "42", name: "Cordless drill", content_type: "qr_two_lines", copies: 1 },
  { app: "spoolman", id: "7", name: "PLA red", content_type: "qr_two_lines", copies: 2 },
];

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem(CART_KEY, JSON.stringify(items));
  localStorage.setItem("lph.printer", PRINTER_B.id);
  reloadCart();
});
afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
  reloadCart();
});

const routes = (layout_defaults: Record<string, unknown> = {}) => ({
  "GET /api/v1/printers": [PRINTER_A, { ...PRINTER_B, paused: false, layout_defaults }],
  [`GET /api/v1/printers/${PRINTER_A.id}/status`]: status(PRINTER_A.id),
  [`GET /api/v1/printers/${PRINTER_B.id}/status`]: status(PRINTER_B.id, { tape_loaded: "62mm", tape_width_mm: 62 }),
  "GET /api/v1/lookup/snipeit/42": { app: "snipeit", id: "42", name: "Cordless drill", url: "https://assets.example.invalid/42", extra: { secondary: ["Shelf 3"] } },
  "POST /api/v1/render/preview": () => pngResponse(),
  [`POST /api/v1/print/${PRINTER_B.id}/batch`]: { batch_id: BATCH, printer_id: PRINTER_B.id, queued_at: "x", job_ids: ["a", "b", "c"] },
  [`GET /api/v1/batches/${BATCH}`]: { id: BATCH, printer_id: PRINTER_B.id, created_by: null, created_at: "x", jobs: [], summary: { total: 3, queued: 3, printing: 0, done: 0, failed: 0, cancelled: 0, all_terminal: false } },
});

describe("the QL 62 mm layout choice in the cart", () => {
  it("previews the first item with the stored default and sends the choice with every item", async () => {
    const { calls } = mockApi(routes({ "62": { orientation: "across", preset: "small_qr" } }));
    await renderApp({ path: "/cart" });
    expect(await screen.findByRole("radio", { name: "Small QR" })).toBeChecked();
    await screen.findByRole("img", { name: "Label preview" });
    const preview = JSON.parse(calls.filter((c) => c.path === "/api/v1/render/preview").at(-1)!.body!);
    expect(preview).toMatchObject({
      tape_mm: 62,
      orientation: "across",
      layout_preset: "small_qr",
      data: { title: "Cordless drill", primary_id: "42", secondary: ["Shelf 3"] },
    });
    await userEvent.click(screen.getByRole("radio", { name: "Standard" }));
    await userEvent.click(screen.getByRole("button", { name: "Print 3 labels" }));
    await screen.findByText(/3 labels sent to Office QL-820NWB/);
    const post = calls.find((c) => c.path === `/api/v1/print/${PRINTER_B.id}/batch`)!;
    const sent = JSON.parse(post.body!).items as { options: Record<string, unknown> }[];
    expect(sent.map((i) => i.options)).toEqual([
      { copies: 1, orientation: "across", layout_preset: "standard" },
      { copies: 2, orientation: "across", layout_preset: "standard" },
    ]);
  });

  it("offers no choice on a P-touch printer and sends the batch as before", async () => {
    localStorage.setItem("lph.printer", PRINTER_A.id);
    const { calls } = mockApi({
      ...routes(),
      [`GET /api/v1/printers/${PRINTER_A.id}/status`]: status(PRINTER_A.id, { tape_loaded: "62mm", tape_width_mm: 62 }),
      [`POST /api/v1/print/${PRINTER_A.id}/batch`]: { batch_id: BATCH, printer_id: PRINTER_A.id, queued_at: "x", job_ids: ["a"] },
    });
    await renderApp({ path: "/cart" });
    await userEvent.click(await screen.findByRole("button", { name: "Print 3 labels" }));
    await vi.waitFor(() => expect(calls.some((c) => c.path === `/api/v1/print/${PRINTER_A.id}/batch`)).toBe(true));
    expect(screen.queryByRole("radiogroup", { name: "Direction" })).toBeNull();
    const post = calls.find((c) => c.path === `/api/v1/print/${PRINTER_A.id}/batch`)!;
    expect(JSON.parse(post.body!).items.map((i: { options: unknown }) => i.options)).toEqual([{ copies: 1 }, { copies: 2 }]);
  });
});
