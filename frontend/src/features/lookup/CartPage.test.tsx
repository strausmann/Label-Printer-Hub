// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderApp, SIGNED_IN } from "../../test-utils";
import { mockApi, PRINTER_A, respond } from "../test-api";
import { CART_KEY, reloadCart } from "./cart";

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
