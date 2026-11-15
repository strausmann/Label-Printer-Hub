// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { act, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { CART_KEY, reloadCart, type CartItem } from "../features/lookup/cart";
import { PRINTER_A, mockApi, status } from "../features/test-api";
import { renderApp } from "../test-utils";
import { cartBadge } from "./CartButton";

const line = (id: string, copies: number): CartItem => ({ app: "grocy", id, name: `Item ${id}`, content_type: "qr_two_lines", copies });

const routes = {
  "GET /api/v1/printers": [PRINTER_A],
  [`GET /api/v1/printers/${PRINTER_A.id}/status`]: status(PRINTER_A.id),
  "GET /api/v1/jobs": [],
};

const store = (items: CartItem[]) => localStorage.setItem(CART_KEY, JSON.stringify(items));
const header = () => screen.getByRole("banner");

// The cart is module state: empty storage first, then take it from storage again.
afterEach(() => {
  localStorage.clear();
  reloadCart();
});

describe("cartBadge", () => {
  it.each([
    [0, null],
    [1, "1"],
    [3, "3"],
    [99, "99"],
    [100, "99+"],
    [1234, "99+"],
  ])("%i entries -> %s", (entries, expected) => {
    expect(cartBadge(entries)).toBe(expected);
  });
});

describe("CartButton: the cart icon in the top bar", () => {
  it("the icon is shown with an empty cart and links to /cart", async () => {
    mockApi(routes);
    await renderApp({ path: "/printers" });
    const link = within(header()).getByRole("link", { name: "Cart, empty" });
    expect(link).toHaveAttribute("href", "/cart");
    expect(within(link).queryByText(/\d/)).toBeNull();
  });

  it("an empty cart is named Cart, empty", async () => {
    mockApi(routes);
    await renderApp({ path: "/printers" });
    expect(within(header()).getByRole("link", { name: "Cart, empty" })).toBeVisible();
  });

  it("the accessible name counts entries, not copies", async () => {
    store([line("7", 3), line("8", 4)]);
    reloadCart();
    mockApi(routes);
    await renderApp({ path: "/printers" });
    const link = within(header()).getByRole("link", { name: "Cart, 2 items" });
    expect(within(link).getByText("2")).toBeInTheDocument();
  });

  it("the badge reads 99+ from 100 entries on while the name keeps the real count", async () => {
    store(Array.from({ length: 100 }, (_, i) => line(String(i), 1)));
    reloadCart();
    mockApi(routes);
    await renderApp({ path: "/printers" });
    const link = within(header()).getByRole("link", { name: "Cart, 100 items" });
    expect(within(link).getByText("99+")).toBeInTheDocument();
  });

  it("says one item in the singular", async () => {
    store([line("7", 5)]);
    reloadCart();
    mockApi(routes);
    await renderApp({ path: "/printers" });
    expect(within(header()).getByRole("link", { name: "Cart, 1 item" })).toBeVisible();
  });

  it("the count follows a storage event from another tab", async () => {
    mockApi(routes);
    await renderApp({ path: "/printers" });
    expect(within(header()).getByRole("link", { name: "Cart, empty" })).toBeVisible();
    act(() => {
      store([line("7", 2)]);
      window.dispatchEvent(new StorageEvent("storage", { key: CART_KEY }));
    });
    expect(await within(header()).findByRole("link", { name: "Cart, 1 item" })).toBeVisible();
  });

  it("says in German what it says in English", async () => {
    store([line("7", 1), line("8", 1)]);
    reloadCart();
    mockApi(routes);
    await renderApp({ path: "/printers", language: "de" });
    expect(within(header()).getByRole("link", { name: "Warenkorb, 2 Einträge" })).toBeVisible();
  });

  it("sits after the bell and before the about link", async () => {
    mockApi(routes);
    await renderApp({ path: "/printers" });
    const names = within(header())
      .getAllByRole("link")
      .concat(within(header()).getAllByRole("button"))
      .sort((a, b) => (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1))
      .map((el) => el.getAttribute("aria-label") ?? "");
    const bell = names.findIndex((n) => n.startsWith("Notifications"));
    const cart = names.findIndex((n) => n.startsWith("Cart"));
    const about = names.findIndex((n) => n.startsWith("About"));
    expect(bell).toBeGreaterThanOrEqual(0);
    expect(cart).toBe(bell + 1);
    expect(about).toBe(cart + 1);
  });
});
