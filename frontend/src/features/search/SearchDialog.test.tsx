// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderApp } from "../../test-utils";
import { DESKTOP_QUERY } from "../../shell/useIsDesktop";
import { job, mockApi, PRINTER_A, PRINTER_B } from "../test-api";

vi.mock("../../shell/pullToRefresh", async (original) => ({ ...(await original<Record<string, unknown>>()), reloadApp: vi.fn().mockResolvedValue(true) }));

let standalone = false;
beforeEach(() => {
  standalone = false;
  // A phone: below 1024 px.
  window.matchMedia = ((query: string) => ({
    matches: query === DESKTOP_QUERY ? false : query === "(display-mode: standalone)" ? standalone : false,
    media: query,
    addEventListener() {},
    removeEventListener() {},
  })) as unknown as typeof window.matchMedia;
});
afterEach(() => {
  delete (window as { matchMedia?: unknown }).matchMedia;
  vi.unstubAllGlobals();
});

const set = (snipeit: boolean, grocy: boolean, spoolman: boolean) => [
  { name: "snipeit" as const, configured: snipeit },
  { name: "grocy" as const, configured: grocy },
  { name: "spoolman" as const, configured: spoolman },
];
const magnifier = () => screen.getByRole("button", { name: "Search" });
const field = () => screen.getByRole("combobox", { name: "Search" });
const dialog = () => screen.getByRole("dialog", { name: "Search" });
const options = () => screen.getAllByRole("option").map((o) => o.textContent);
const item = (app: string, id: string) => ({ app, id, name: "Cordless drill", url: `https://assets.example.invalid/${app}/${id}`, extra: {} });

async function openDialog() {
  await userEvent.click(magnifier());
  await screen.findByRole("dialog", { name: "Search" });
}

describe("search dialog (below 1024 px)", () => {
  it("below 1024 px a Search button replaces the field", async () => {
    mockApi({});
    await renderApp({ path: "/", info: { integrations: set(true, true, true) } });
    expect(screen.queryByRole("combobox", { name: "Search" })).toBeNull();
    expect(within(screen.getByRole("banner")).getByRole("button", { name: "Search" })).toBeVisible();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("the dialog opens with the field focused", async () => {
    mockApi({});
    await renderApp({ path: "/", info: { integrations: set(true, true, true) } });
    await openDialog();
    expect(field()).toHaveFocus();
    expect(field()).toHaveValue("");
    expect(within(dialog()).getByRole("button", { name: "Close" })).toBeVisible();
  });

  it("typing shows the same results as the inline search", async () => {
    const wanted = job("0f3a9c1e-7b2d-4e5f-8a6b-1c2d3e4f5a6b", PRINTER_A.id, "queued", { template_key: "asset-label" });
    const api = { "GET /api/v1/printers": [PRINTER_A, PRINTER_B], "GET /api/v1/jobs": [wanted] };
    mockApi(api);
    await renderApp({ path: "/", info: { integrations: set(true, false, false) } });
    await openDialog();
    await userEvent.type(field(), "office");
    const list = await screen.findByRole("listbox", { name: "Search results" });
    await within(list).findByRole("option", { name: /Office QL-820NWB/ });
    // The same titles in the same order as GlobalSearch.test.tsx gives for this source set.
    expect(options()).toEqual(["Look up office in Snipe-IT", "Office QL-820NWBoffice-ql"]);
    expect(within(list).getByText("Printers")).toBeVisible();
    expect(within(list).getByText("Look up in an integration")).toBeVisible();
    expect(screen.getAllByRole("option")[0]).toHaveAttribute("aria-selected", "true");
  });

  it("Enter opens the first result and closes the dialog, focus back on the magnifier", async () => {
    mockApi({ "GET /api/v1/lookup/snipeit/42": item("snipeit", "42"), "GET /api/v1/printers": [] });
    const { router } = await renderApp({ path: "/", info: { integrations: set(true, true, true) } });
    await openDialog();
    await userEvent.type(field(), "42{Enter}");
    expect(router.state.location.pathname).toBe("/lookup/snipeit/42");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(magnifier()).toHaveFocus());
  });

  it("clicking a result opens it and closes the dialog", async () => {
    mockApi({ "GET /api/v1/lookup/spoolman/5": item("spoolman", "5"), "GET /api/v1/printers": [] });
    const { router } = await renderApp({ path: "/", info: { integrations: set(false, false, true) } });
    await openDialog();
    await userEvent.type(field(), "5");
    await userEvent.click(await screen.findByRole("option", { name: "Look up 5 in Spoolman" }));
    expect(router.state.location.pathname).toBe("/lookup/spoolman/5");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("the first Escape closes the results, the second the dialog", async () => {
    mockApi({});
    await renderApp({ path: "/", info: { integrations: set(true, false, false) } });
    await openDialog();
    await userEvent.type(field(), "42");
    await screen.findByRole("listbox");
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(screen.getByRole("dialog", { name: "Search" })).toBeVisible();
    expect(field()).toHaveValue("42");
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(magnifier()).toHaveFocus());
  });

  it("the close button closes it", async () => {
    mockApi({});
    await renderApp({ path: "/", info: { integrations: set(true, false, false) } });
    await openDialog();
    await userEvent.click(within(dialog()).getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("a press on the dim area closes it", async () => {
    mockApi({});
    await renderApp({ path: "/", info: { integrations: set(true, false, false) } });
    await openDialog();
    const layer = dialog().parentElement!.parentElement!; // dialog > modal > overlay
    expect(layer).toHaveClass("fixed");
    fireEvent.pointerDown(layer, { pointerId: 1, isPrimary: true, button: 0 });
    fireEvent.pointerUp(layer, { pointerId: 1, isPrimary: true, button: 0 });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("every opening starts with an empty field", async () => {
    mockApi({});
    await renderApp({ path: "/", info: { integrations: set(true, false, false) } });
    await openDialog();
    await userEvent.type(field(), "42");
    await userEvent.keyboard("{Escape}{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await openDialog();
    expect(field()).toHaveValue("");
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("a window that grows to a desktop closes the dialog for good", async () => {
    const listeners = new Set<() => void>();
    let desktop = false;
    window.matchMedia = ((query: string) => ({
      matches: query === DESKTOP_QUERY ? desktop : false,
      media: query,
      addEventListener: (_: string, fn: () => void) => listeners.add(fn),
      removeEventListener: (_: string, fn: () => void) => listeners.delete(fn),
    })) as unknown as typeof window.matchMedia;
    mockApi({});
    await renderApp({ path: "/", info: { integrations: set(true, false, false) } });
    await openDialog();
    desktop = true;
    act(() => listeners.forEach((fn) => fn()));
    await screen.findByRole("combobox", { name: "Search" });
    expect(screen.queryByRole("dialog")).toBeNull();
    desktop = false;
    act(() => listeners.forEach((fn) => fn()));
    expect(await screen.findByRole("button", { name: "Search" })).toBeVisible();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("slash opens the dialog; a slash typed into the field is just text", async () => {
    mockApi({});
    await renderApp({ path: "/", info: { integrations: set(true, false, false) } });
    expect(screen.queryByRole("dialog")).toBeNull();
    await userEvent.keyboard("/");
    await screen.findByRole("dialog", { name: "Search" });
    expect(field()).toHaveFocus();
    expect(field()).toHaveValue("");
    await userEvent.keyboard("a/b");
    expect(field()).toHaveValue("a/b");
  });

  it("pull to refresh stays out of the open dialog", async () => {
    standalone = true;
    const { reloadApp } = await import("../../shell/pullToRefresh");
    vi.mocked(reloadApp).mockClear();
    mockApi({});
    await renderApp({ path: "/", info: { integrations: set(true, false, false) } });
    await openDialog();
    // Not from the text field (a focused field blocks the pull on its own): only the open dialog is left to stop it.
    within(dialog()).getByRole("button", { name: "Close" }).focus();
    expect(field()).not.toHaveFocus();
    const touch = (type: string, y: number) => {
      const event = new Event(type, { bubbles: true, cancelable: true });
      Object.defineProperty(event, "touches", { value: type === "touchend" ? [] : [{ clientX: 100, clientY: y }] });
      act(() => {
        dialog().dispatchEvent(event);
      });
      return event;
    };
    touch("touchstart", 100);
    touch("touchmove", 160);
    expect(touch("touchmove", 300).defaultPrevented).toBe(false);
    touch("touchend", 0);
    expect(reloadApp).not.toHaveBeenCalled();
    expect(screen.queryByTestId("pull-indicator")?.getAttribute("data-armed") ?? "false").toBe("false");
  });
});
