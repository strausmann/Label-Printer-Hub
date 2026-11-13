import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, vi } from "vitest";
import { renderApp } from "../../../test-utils";
import { CART_KEY, reloadCart } from "../../lookup/cart";
import { mockApi, type Call } from "../../test-api";
import { P, routes } from "./testkit";

// What the SheetSection test files share. Every test boots the whole app (about 1 s alone before the first
// assertion) and each click re-renders it, so the sheet section is tested in several files that vitest runs
// side by side, split by concern: this one holds the setup they have in common.

export const PREVIEW = `/api/v1/print/${P}/sheet/preview`;
export const PRINT = `/api/v1/print/${P}/sheet`;

/** Registers the per-test reset every file here needs: no stored cart, no stubbed globals. Call it at the top of the file. */
export function resetBetweenTests(): void {
  beforeEach(() => {
    localStorage.clear();
    reloadCart();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    localStorage.clear();
    reloadCart();
  });
}

export const previews = (calls: Call[]) => calls.filter((c) => c.path === PREVIEW);
export const printCalls = (calls: Call[]) => calls.filter((c) => c.path === PRINT && c.method === "POST");

/** The item view of Flour (Grocy 7) with a page printer first in the list. */
export async function itemView(r: Record<string, unknown> = routes(), copies = 9) {
  const api = mockApi(r);
  const view = await renderApp({ path: "/lookup/grocy/7" });
  await screen.findByRole("heading", { level: 2, name: "Print onto a sheet" });
  if (copies !== 1) {
    fireEvent.change(screen.getByRole("spinbutton", { name: "Copies" }), { target: { value: String(copies) } });
  }
  return { ...api, ...view };
}

export async function cartView(path: string, items: Array<Record<string, unknown>>, r: Record<string, unknown> = routes()) {
  localStorage.setItem(CART_KEY, JSON.stringify(items));
  reloadCart();
  const api = mockApi(r);
  const view = await renderApp({ path });
  return { ...api, ...view };
}
/** Presses the print button once the preview has arrived and enabled it. */
export async function pressPrint(name: string | RegExp = "Print onto sheet") {
  const button = await screen.findByRole("button", { name });
  await waitFor(() => expect(button).toBeEnabled());
  await userEvent.click(button);
}
export const LINE = (id: string, copies: number, name = `Item ${id}`, app = "grocy") => ({ app, id, name, content_type: "qr_two_lines", copies });
