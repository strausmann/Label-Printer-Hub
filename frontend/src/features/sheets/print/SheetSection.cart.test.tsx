// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { CART_KEY } from "../../lookup/cart";
import { sheet, routes } from "./testkit";
import { LINE, cartView, itemView, resetBetweenTests } from "./SheetSection.kit";
import { lastType } from "./lastType";
import { PAGE_PRINTER } from "../../test-api";
import type * as Debounced from "./useDebounced";

vi.mock("./useDebounced", async (importOriginal) => {
  const real = await importOriginal<typeof Debounced>();
  return { useDebounced: <T,>(value: T, ms: number) => real.useDebounced(value, Math.min(ms, 20)) };
});
vi.setConfig({ testTimeout: 15_000 });
resetBetweenTests();

const section = () => screen.getByRole("region", { name: "Print onto a sheet" });
const addButton = () => within(section()).getByRole("button", { name: "Add to cart" });
const stored = () => JSON.parse(localStorage.getItem(CART_KEY) ?? "[]") as Array<{ id: string; copies: number }>;

describe("Add to cart in the sheet section", () => {
  it("puts the item with its copies into the cart once", async () => {
    await itemView(routes(), 3);
    await waitFor(() => expect(addButton()).toBeEnabled());
    await userEvent.click(addButton());
    expect(stored()).toEqual([expect.objectContaining({ id: "7", copies: 3 })]);
  });

  it("remembers the sheet type for the printer", async () => {
    await itemView(routes(), 1);
    await waitFor(() => expect(addButton()).toBeEnabled());
    expect(lastType.get(PAGE_PRINTER.id)).toBeNull();
    await userEvent.click(addButton());
    expect(lastType.get(PAGE_PRINTER.id)).toBe("L4736REV");
  });

  it("after adding, Open cart links to the chosen sheet and tray", async () => {
    await itemView(routes(), 1);
    await waitFor(() => expect(addButton()).toBeEnabled());
    await userEvent.click(addButton());
    const link = await within(section()).findByRole("link", { name: "Open cart" });
    expect(link).toHaveAttribute("href", "/cart?sheet=L4736-0001&tray=main");
  });

  it("the status line goes away when the sheet changes", async () => {
    await itemView(routes({ sheets: [sheet("L4736-0001", 17), sheet("L4736-0002", 3)] }), 1);
    await waitFor(() => expect(addButton()).toBeEnabled());
    await userEvent.click(addButton());
    await within(section()).findByRole("link", { name: "Open cart" });
    await userEvent.click(within(section()).getByRole("combobox", { name: "Sheet" }));
    await userEvent.click(await screen.findByRole("option", { name: /L4736-0002/ }));
    await waitFor(() => expect(within(section()).queryByRole("link", { name: "Open cart" })).toBeNull());
  });

  it("without addToCart there is no Add to cart button in the section", async () => {
    await cartView("/cart", [LINE("1", 2)]);
    const cartSection = await screen.findByRole("region", { name: "Print onto a sheet" });
    expect(within(cartSection).queryByRole("button", { name: "Add to cart" })).toBeNull();
  });

  it("the button is described by the section heading", async () => {
    await itemView(routes(), 1);
    expect(addButton()).toHaveAccessibleDescription("Print onto a sheet");
  });

  it("the button is disabled until the target is known", async () => {
    const never = new Promise<Response>(() => {});
    await itemView(routes({ extra: { "GET /api/v1/sheets": () => never } }), 1);
    expect(addButton()).toBeDisabled();
  });
});

describe("the tray from the cart address", () => {
  const tray = () => screen.findByRole("button", { name: /Tray/ });

  it("the tray from the address is preselected in the sheet section", async () => {
    await cartView("/cart?tray=bypass", [LINE("1", 2)]);
    expect(await tray()).toHaveTextContent("Bypass");
  });

  it("a tray in the address is applied when the status arrives later", async () => {
    const slow = routes();
    const { pageStatus, PAGE_PRINTER } = await import("../../test-api");
    slow[`GET /api/v1/printers/${PAGE_PRINTER.id}/status`] = async () => {
      await new Promise((r) => setTimeout(r, 150));
      return pageStatus(PAGE_PRINTER.id);
    };
    await cartView("/cart?tray=bypass", [LINE("1", 2)], slow);
    await waitFor(async () => expect(await tray()).toHaveTextContent("Bypass"));
  });

  it("an unknown tray in the address is ignored", async () => {
    await cartView("/cart?tray=nope", [LINE("1", 2)]);
    expect(await tray()).toHaveTextContent("Main tray");
  });
});
