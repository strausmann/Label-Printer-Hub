// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { APP_WAIT, renderApp, SIGNED_IN, widenAppWaits } from "../../test-utils";
import type * as Ql from "../layout/ql";
import { mockApi, pngResponse, PRINTER_B, PRINTER_A, respond, status } from "../test-api";
import { CART_KEY, reloadCart } from "./cart";

// The check and the previews are asked for 400 ms after the last change (PREVIEW_DEBOUNCE_MS, tested in
// layout/ql.test.ts). With the real wait a test spent 400 ms of findBy's 1 s window doing nothing, and failed on a
// loaded runner; here it is cut to 20 ms.
vi.mock("../layout/ql", async (importOriginal) => {
  const real = await importOriginal<typeof Ql>();
  return { ...real, useDebounced: <T,>(value: T, ms: number) => real.useDebounced(value, Math.min(ms, 20)) };
});

// Each test boots the whole app; the per-test limit is widened for this file only (vi.setConfig is file-scoped).
vi.setConfig({ testTimeout: 15_000 });
widenAppWaits();

const BATCH = "cccccccc-0000-4000-8000-000000000001";
const items = [
  { app: "snipeit", id: "42", name: "Cordless drill", content_type: "qr_two_lines", copies: 1 },
  { app: "spoolman", id: "7", name: "PLA red", content_type: "qr_two_lines", copies: 2 },
];

beforeEach(() => {
  localStorage.setItem(CART_KEY, JSON.stringify(items));
  reloadCart();
});
afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
  reloadCart();
});

const routes = (extra: Record<string, unknown> = {}) => ({
  "GET /api/v1/printers": [PRINTER_A],
  [`POST /api/v1/print/${PRINTER_A.id}/batch`]: { batch_id: BATCH, printer_id: PRINTER_A.id, queued_at: "x", job_ids: ["a", "b", "c"] },
  [`GET /api/v1/batches/${BATCH}`]: { id: BATCH, printer_id: PRINTER_A.id, created_by: null, created_at: "x", jobs: [], summary: { total: 3, queued: 3, printing: 0, done: 0, failed: 0, cancelled: 0, all_terminal: false } },
  ...extra,
});

describe("CartPage", () => {
  it("lists the items with their app and id", async () => {
    mockApi(routes());
    await renderApp({ path: "/cart" });
    const list = await screen.findByRole("list", { name: "Cart" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(2);
    expect(within(list).getByText("PLA red")).toBeVisible();
    expect(screen.getByRole("button", { name: "Print 3 labels" })).toBeEnabled();
  });

  it("asks for no printer status while no printer is selected", async () => {
    const { calls } = mockApi(routes({ "GET /api/v1/printers": [] }));
    await renderApp({ path: "/cart" });
    await screen.findByRole("list", { name: "Cart" });
    expect(calls.filter((c) => /\/printers\/\/status/.test(c.path))).toEqual([]);
  });

  it("prints everything as one batch and empties the cart", async () => {
    const { calls } = mockApi(routes());
    await renderApp({ path: "/cart" });
    await userEvent.click(await screen.findByRole("button", { name: "Print 3 labels" }));
    expect(await screen.findByText(/3 labels sent to Workshop PT-P750W/)).toBeVisible();
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(1);
    expect(screen.queryByRole("list", { name: "Cart" })).toBeNull();
    expect(localStorage.getItem(CART_KEY)).toBe("[]");
  });

  it("keeps the cart and says why when the batch is rejected", async () => {
    mockApi(routes({ [`POST /api/v1/print/${PRINTER_A.id}/batch`]: respond(409, { detail: { error_code: "no_tape_loaded", error_message: "No tape is loaded." } }) }));
    await renderApp({ path: "/cart" });
    await userEvent.click(await screen.findByRole("button", { name: "Print 3 labels" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("No tape is loaded.");
    expect(screen.getByRole("list", { name: "Cart" })).toBeVisible();
  });

  it("read key cannot print from cart", async () => {
    const { calls } = mockApi(routes());
    await renderApp({ path: "/cart", session: { ...SIGNED_IN, scope: "read" } });
    const print = await screen.findByRole("button", { name: "Print 3 labels" });
    expect(print).toBeDisabled();
    expect(screen.getByText("Printing needs a print or admin key.")).toBeVisible();
    await userEvent.click(print);
    expect(calls.filter((c) => c.method === "POST")).toEqual([]);
  });

  it("refused tape print is localized", async () => {
    const refusal = (code: string, detail: Record<string, unknown> | null) => respond(422, { detail: { error_code: code, error_message: "English sentence from the server.", error_detail: detail } });
    mockApi(routes({ [`POST /api/v1/print/${PRINTER_A.id}/batch`]: refusal("qr_payload_too_long", { length: 700, max_bytes: 512 }) }));
    const first = await renderApp({ path: "/cart" });
    await userEvent.click(await screen.findByRole("button", { name: "Print 3 labels" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The link in the QR code is 700 bytes long, but this layout holds at most 512 bytes.");
    expect(alert).not.toHaveTextContent("English sentence");
    first.unmount();

    mockApi(routes({ [`POST /api/v1/print/${PRINTER_A.id}/batch`]: refusal("conflicting_orientation", { orientations: ["along", "across"] }) }));
    await renderApp({ path: "/cart" });
    await userEvent.click(await screen.findByRole("button", { name: "Print 3 labels" }));
    const second = await screen.findByRole("alert");
    expect(second).toHaveTextContent("These labels ask for different directions (along and across). Print them in separate runs.");
    expect(second).not.toHaveTextContent("English sentence");
  });

  it("removes an item and changes copies", async () => {
    mockApi(routes());
    await renderApp({ path: "/cart" });
    await userEvent.click(await screen.findByRole("button", { name: "Remove Cordless drill" }));
    expect(screen.queryByText("Cordless drill")).toBeNull();
    expect(screen.getByRole("button", { name: "Print 2 labels" })).toBeVisible();
  });

  it("an empty cart says so and offers no print button", async () => {
    localStorage.setItem(CART_KEY, "[]");
    reloadCart();
    mockApi(routes());
    await renderApp({ path: "/cart" });
    expect(await screen.findByText("The cart is empty.")).toBeVisible();
    expect(screen.queryByRole("button", { name: /^Print/ })).toBeNull();
  });
});

describe("CartPage checks and previews", () => {
  const QL = { tape_loaded: "62mm", tape_width_mm: 62 };
  const lookup = (app: string, id: string, name: string) => ({ app, id, name, url: `https://assets.example.invalid/${id}`, extra: { secondary: [] } });
  const pass = (n: number) => ({ results: Array.from({ length: n }, (_, index) => ({ index, ok: true })) });
  const qlRoutes = (cart: unknown[], extra: Record<string, unknown> = {}) => {
    localStorage.setItem(CART_KEY, JSON.stringify(cart));
    localStorage.setItem("lph.printer", PRINTER_B.id);
    reloadCart();
    return {
      "GET /api/v1/printers": [PRINTER_A, { ...PRINTER_B, paused: false }],
      [`GET /api/v1/printers/${PRINTER_B.id}/status`]: status(PRINTER_B.id, QL),
      "GET /api/v1/lookup/snipeit/1": lookup("snipeit", "1", "Item one"),
      "GET /api/v1/lookup/snipeit/2": lookup("snipeit", "2", "Item two"),
      "GET /api/v1/lookup/snipeit/3": lookup("snipeit", "3", "Item three"),
      "POST /api/v1/render/preview": () => pngResponse(),
      "POST /api/v1/render/check": pass(cart.length),
      ...extra,
    };
  };
  const line = (id: string, content_type: string) => ({ app: "snipeit", id, name: `Item ${id === "1" ? "one" : id === "2" ? "two" : "three"}`, content_type, copies: 1 });
  const TOO_LONG = { results: [{ index: 0, ok: false, error_code: "qr_payload_too_long", error_detail: { length: 812, max_bytes: 122 }, error_message: "English sentence from the server." }] };

  it("shows one preview per content type", async () => {
    mockApi(qlRoutes([line("1", "qr_two_lines"), line("2", "qr_two_lines"), line("3", "qr_only")]));
    await renderApp({ path: "/cart" });
    await vi.waitFor(() => expect(screen.getAllByRole("img", { name: "Label preview" })).toHaveLength(2), APP_WAIT);
    expect(screen.getByRole("region", { name: "Preview of Item one" })).toBeVisible();
    expect(screen.getByRole("region", { name: "Preview of Item three" })).toBeVisible();
    expect(screen.queryByRole("region", { name: "Preview of Item two" })).toBeNull();
  });

  it("says how many layouts are not shown", async () => {
    const types = ["qr_only", "qr_one_line", "qr_two_lines", "qr_three_lines", "text_one_line", "text_two_lines"];
    const cart = types.map((type, n) => ({ app: "snipeit", id: String(n + 1), name: `Item ${n + 1}`, content_type: type, copies: 1 }));
    mockApi(qlRoutes(cart, { "POST /api/v1/render/check": pass(6) }));
    await renderApp({ path: "/cart" });
    expect(await screen.findByText("2 more layouts are not shown.")).toBeVisible();
    expect(screen.getAllByRole("region", { name: /^Preview of / })).toHaveLength(4);
  });

  it("flags an item whose QR code does not fit", async () => {
    const { calls } = mockApi(qlRoutes([line("1", "qr_two_lines")], { "POST /api/v1/render/check": TOO_LONG }));
    await renderApp({ path: "/cart" });
    const row = within(await screen.findByRole("list", { name: "Cart" })).getByRole("listitem");
    expect(await within(row).findByText("The QR code does not fit this tape: 812 of at most 122 bytes.")).toBeVisible();
    expect(row).not.toHaveTextContent("English sentence");
    expect(row).toHaveAccessibleDescription("The QR code does not fit this tape: 812 of at most 122 bytes.");
    const body = JSON.parse(calls.find((c) => c.path === "/api/v1/render/check")!.body!);
    expect(body).toMatchObject({ tape_mm: 62, items: [{ content_type: "qr_two_lines", lookup: { app: "snipeit", identifier: "1" } }] });
  });

  it("flags only the items the check refused", async () => {
    const two = { results: [{ index: 0, ok: true }, { index: 1, ok: false, error_code: "integration_item_not_found" }] };
    mockApi(qlRoutes([line("1", "qr_two_lines"), line("2", "qr_one_line")], { "POST /api/v1/render/check": two }));
    await renderApp({ path: "/cart" });
    const rows = within(await screen.findByRole("list", { name: "Cart" })).getAllByRole("listitem");
    expect(await within(rows[1]!).findByText("This item no longer exists in its app.")).toBeVisible();
    expect(rows[0]).not.toHaveAccessibleDescription();
    expect(screen.getByText("1 item will not print.")).toBeVisible();
  });

  it("says in words why an item cannot be drawn when the server names no tape problem", async () => {
    const two = {
      results: [
        { index: 0, ok: false, error_code: "content_type_data_mismatch", error_message: "English sentence from the server." },
        { index: 1, ok: false, error_code: "render_failed", error_message: "English sentence from the server." },
      ],
    };
    mockApi(qlRoutes([line("1", "qr_two_lines"), line("2", "qr_one_line")], { "POST /api/v1/render/check": two }));
    await renderApp({ path: "/cart" });
    const rows = within(await screen.findByRole("list", { name: "Cart" })).getAllByRole("listitem");
    expect(await within(rows[0]!).findByText("This item has no data for this layout.")).toBeVisible();
    expect(await within(rows[1]!).findByText("The label could not be drawn for this tape.")).toBeVisible();
    expect(screen.queryByText(/English sentence/)).toBeNull();
  });

  it("summarises the items that will not print", async () => {
    mockApi(qlRoutes([line("1", "qr_two_lines")], { "POST /api/v1/render/check": TOO_LONG }));
    await renderApp({ path: "/cart" });
    expect(await screen.findByText("1 item will not print.")).toBeVisible();
  });

  it("the print button stays enabled with a flag", async () => {
    mockApi(qlRoutes([line("1", "qr_two_lines")], { "POST /api/v1/render/check": TOO_LONG }));
    await renderApp({ path: "/cart" });
    await screen.findByText("1 item will not print.");
    expect(screen.getByRole("button", { name: "Print 1 label" })).toBeEnabled();
  });

  it("a failed check shows no flags", async () => {
    mockApi(qlRoutes([line("1", "qr_two_lines")], { "POST /api/v1/render/check": respond(429, { detail: { error_code: "rate_limit_exceeded", error_message: "Slow down." } }) }));
    await renderApp({ path: "/cart" });
    expect(await screen.findByText("Could not check the items; the print still checks them.")).toBeVisible();
    expect(screen.queryByText(/will not print/)).toBeNull();
    expect(screen.getByRole("button", { name: "Print 1 label" })).toBeEnabled();
  });

  it("no check without a known tape", async () => {
    const { calls } = mockApi(
      qlRoutes([line("1", "qr_two_lines")], { [`GET /api/v1/printers/${PRINTER_B.id}/status`]: status(PRINTER_B.id, { tape_loaded: null, tape_width_mm: null }) }),
    );
    await renderApp({ path: "/cart" });
    await screen.findByRole("list", { name: "Cart" });
    await vi.waitFor(() => expect(calls.some((c) => c.path === `/api/v1/printers/${PRINTER_B.id}/status`)).toBe(true));
    expect(calls.filter((c) => c.path === "/api/v1/render/check")).toEqual([]);
  });
});

describe("spool labels in the cart (#346)", () => {
  const SWATCH = { spool_id: 7, language: "en", vendor: "TecBears", title: "PETG", color_name: "Orange", color_hexes: ["FF5F00"] };
  const spoolLine = (id: string) => ({ app: "spoolman", id, name: `Spool ${id}`, content_type: "spool_swatch", copies: 1 });
  const otherLine = { app: "snipeit", id: "1", name: "Item one", content_type: "qr_two_lines", copies: 1 };
  const cartRoutes = (cart: unknown[]) => {
    localStorage.setItem(CART_KEY, JSON.stringify(cart));
    localStorage.setItem("lph.printer", PRINTER_B.id);
    reloadCart();
    return {
      "GET /api/v1/printers": [PRINTER_A, { ...PRINTER_B, paused: false }],
      [`GET /api/v1/printers/${PRINTER_B.id}/status`]: status(PRINTER_B.id, { tape_loaded: "62mm", tape_width_mm: 62 }),
      "GET /api/v1/lookup/snipeit/1": { app: "snipeit", id: "1", name: "Item one", url: "https://assets.example.invalid/1", extra: {} },
      "GET /api/v1/lookup/spoolman/7": { app: "spoolman", id: "7", name: "Spool 7", url: "https://spoolman.example.invalid/spool/show/7", extra: { swatch: SWATCH } },
      "GET /api/v1/lookup/spoolman/8": { app: "spoolman", id: "8", name: "Spool 8", url: "https://spoolman.example.invalid/spool/show/8", extra: { swatch: { ...SWATCH, spool_id: 8 } } },
      "POST /api/v1/render/preview": () => pngResponse(),
      "POST /api/v1/render/check": { results: cart.map((_, index) => ({ index, ok: true })) },
      [`POST /api/v1/print/${PRINTER_B.id}/batch`]: { batch_id: "cccccccc-0000-4000-8000-000000000001", printer_id: PRINTER_B.id, queued_at: "x", job_ids: ["a", "b"] },
    };
  };

  it("a cart of spool labels hides the layout picker", async () => {
    const { calls } = mockApi(cartRoutes([spoolLine("7"), spoolLine("8")]));
    await renderApp({ path: "/cart" });
    await screen.findByRole("img", { name: "Label preview" });
    expect(screen.queryByRole("radiogroup", { name: "Direction" })).toBeNull();
    const preview = JSON.parse(calls.filter((c) => c.path === "/api/v1/render/preview").at(-1)!.body!);
    expect(preview).toMatchObject({ content_type: "spool_swatch", data: { swatch: SWATCH } });
    expect(preview).not.toHaveProperty("orientation");
  });

  it("a mixed cart keeps the picker and sends the swatch item without orientation", async () => {
    const { calls } = mockApi(cartRoutes([otherLine, spoolLine("7")]));
    await renderApp({ path: "/cart" });
    expect(await screen.findByRole("radiogroup", { name: "Direction" })).toBeVisible();
    await waitFor(() => expect(calls.filter((c) => c.path === "/api/v1/render/preview").length).toBeGreaterThanOrEqual(2));
    const previews = calls.filter((c) => c.path === "/api/v1/render/preview").map((c) => JSON.parse(c.body!));
    const swatchPreview = previews.find((p) => p.content_type === "spool_swatch");
    expect(swatchPreview).toBeDefined();
    expect(swatchPreview).not.toHaveProperty("orientation");
    await userEvent.click(screen.getByRole("radio", { name: "Along" }));
    await userEvent.click(screen.getByRole("button", { name: "Print 2 labels" }));
    await screen.findByText(/2 labels sent to Office QL-820NWB/);
    const post = calls.find((c) => c.path === `/api/v1/print/${PRINTER_B.id}/batch`)!;
    const sent = JSON.parse(post.body!).items as { content_type: string; options: Record<string, unknown> }[];
    expect(sent).toEqual([
      { content_type: "qr_two_lines", options: { copies: 1, orientation: "along" }, lookup: { app: "snipeit", identifier: "1" } },
      { content_type: "spool_swatch", options: { copies: 1 }, lookup: { app: "spoolman", identifier: "7" } },
    ]);
  });

  it("on 38 mm tape the other labels are flagged and a print names why", async () => {
    const routes = cartRoutes([otherLine, spoolLine("7")]);
    const { calls } = mockApi({
      ...routes,
      [`GET /api/v1/printers/${PRINTER_B.id}/status`]: status(PRINTER_B.id, { tape_loaded: "38mm", tape_width_mm: 38 }),
      "POST /api/v1/render/check": {
        results: [
          { index: 0, ok: false, error_code: "unsupported_tape", error_message: "x", error_detail: { tape_mm: 38, spool_label_only: true } },
          { index: 1, ok: true },
        ],
      },
      [`POST /api/v1/print/${PRINTER_B.id}/batch`]: respond(409, {
        detail: { error_code: "unsupported_tape", error_message: "x", error_detail: { tape_mm: 38, content_types: ["qr_two_lines"] } },
      }),
    });
    await renderApp({ path: "/cart" });
    expect(await screen.findByText("Only the spool label prints on 38 mm tape. Remove this label or load 62 mm tape.")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: /Print 2 labels/ }));
    expect(
      await screen.findByText("Only the spool label prints on 38 mm tape. Remove the other labels from the cart or load 62 mm tape."),
    ).toBeVisible();
    expect(calls.some((c) => c.path === `/api/v1/print/${PRINTER_B.id}/batch`)).toBe(true);
  });
});
