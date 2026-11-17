// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { act, cleanup, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { noteServerVersion, resetUpdatesForTest, setVersionCheckForTest } from "../app/updates";
import { mockApi } from "../features/test-api";
import { renderApp } from "../test-utils";

// A page built for 1.5.0 talking to a hub that reports 1.6.0.
const BUILT_FOR = "1.5.0";
const SERVER = "1.6.0";

let reload: Mock<() => void>;

beforeEach(() => {
  reload = vi.fn<() => void>();
  setVersionCheckForTest({ buildVersion: BUILT_FOR, reload });
});

afterEach(() => {
  resetUpdatesForTest();
  vi.unstubAllGlobals();
  document.documentElement.style.removeProperty("--update-toast-h");
  document.querySelectorAll("[data-test-field]").forEach((node) => node.remove());
});

const toast = () => screen.queryByRole("region", { name: "New version" });
const sidebar = () => screen.getByRole("complementary");
const sidebarReload = () => within(sidebar()).queryByRole("button", { name: "Reload new version" });

/** `matchMedia` that answers the coarse-pointer query with `coarse` and every other query with false. */
function stubPointer(coarse: boolean) {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: coarse && query === "(pointer: coarse)",
    media: query,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  }));
}

/** A control outside the app, standing in for any field or button the person focuses. */
function control(tag: string, attributes: Record<string, string> = {}): HTMLElement {
  const node = document.createElement(tag);
  node.dataset.testField = "";
  for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
  document.body.append(node);
  return node;
}

async function showUpdate() {
  // The bell lists entries once its sources answer.
  mockApi({ "GET /api/v1/printers": [], "GET /api/v1/jobs": [] });
  await renderApp({ path: "/" });
  await act(async () => noteServerVersion(SERVER));
}

describe("the update notice", () => {
  it("toast, sidebar box and entry appear together", async () => {
    await showUpdate();
    const region = toast();
    expect(region).not.toBeNull();
    expect(within(region!).getByText("New version available")).toBeVisible();
    expect(within(region!).getByText(`Version ${SERVER}`)).toBeVisible();
    expect(sidebarReload()).not.toBeNull();
    expect(within(sidebar()).getByText(`${SERVER} ready`)).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: /^Notifications/ }));
    const panel = await screen.findByRole("dialog");
    expect(within(panel).getByText(`New version ${SERVER} available`)).toBeVisible();
  });

  it("no update strip in the page content", async () => {
    await showUpdate();
    const main = screen.getByRole("main");
    expect(within(main).queryByText("New version available")).toBeNull();
    expect(within(main).queryByRole("button", { name: /Reload/ })).toBeNull();
  });

  it("Later hides only the toast", async () => {
    await showUpdate();
    await userEvent.click(within(toast()!).getByRole("button", { name: "Later" }));
    expect(toast()).toBeNull();
    expect(sidebarReload()).not.toBeNull();
    expect(reload).not.toHaveBeenCalled();
  });

  it("the toast is polite", async () => {
    await showUpdate();
    const region = toast()!;
    expect(within(region).getByRole("status")).toHaveTextContent("New version available");
    expect(within(region).queryByRole("alert")).toBeNull();
    expect(region.closest("[aria-live=assertive]")).toBeNull();
  });

  it("Reload in each place calls applyUpdate once", async () => {
    // Without a service worker applyUpdate reloads at once: one reload per press is one applyUpdate.
    const presses: [string, () => Promise<HTMLElement>][] = [
      ["toast", async () => within(toast()!).getByRole("button", { name: "Reload" })],
      ["sidebar", async () => sidebarReload()!],
      [
        "entry",
        async () => {
          await userEvent.click(screen.getByRole("button", { name: /^Notifications/ }));
          const panel = await screen.findByRole("dialog");
          return within(panel).getByRole("button", { name: "Reload new version" });
        },
      ],
    ];
    for (const [place, find] of presses) {
      resetUpdatesForTest();
      reload = vi.fn<() => void>();
      setVersionCheckForTest({ buildVersion: BUILT_FOR, reload });
      await showUpdate();
      await userEvent.click(await find());
      await vi.waitFor(() => expect(reload, place).toHaveBeenCalledTimes(1));
      cleanup();
    }
  });

  it("a focused text field on a touch device hides the toast", async () => {
    stubPointer(true);
    await showUpdate();
    expect(toast()).not.toBeNull();
    const field = control("input", { type: "text", "aria-label": "Code" });
    await act(async () => field.focus());
    expect(toast()).toBeNull();
    // The box in the sidebar is not in the way of the keyboard and stays.
    expect(sidebarReload()).not.toBeNull();
    await act(async () => field.blur());
    expect(toast()).not.toBeNull();
  });

  it("a focused field with a fine pointer keeps the toast", async () => {
    stubPointer(false);
    await showUpdate();
    const field = control("textarea", { "aria-label": "Notes" });
    await act(async () => field.focus());
    expect(toast()).not.toBeNull();
  });

  it("a focused button keeps the toast", async () => {
    stubPointer(true);
    await showUpdate();
    const button = control("button", { type: "button", "aria-label": "Print" });
    await act(async () => button.focus());
    expect(toast()).not.toBeNull();
    const box = control("input", { type: "checkbox", "aria-label": "Pick" });
    await act(async () => box.focus());
    expect(toast()).not.toBeNull();
  });

  it("a shrunken visual viewport hides the toast", async () => {
    vi.stubGlobal("innerHeight", 800);
    const listeners = new Set<() => void>();
    const vv = {
      height: 800,
      offsetTop: 0,
      addEventListener: (_type: string, listener: () => void) => listeners.add(listener),
      removeEventListener: (_type: string, listener: () => void) => listeners.delete(listener),
    };
    vi.stubGlobal("visualViewport", vv);
    await showUpdate();
    expect(toast()).not.toBeNull();
    vv.height = 400;
    await act(async () => listeners.forEach((l) => l()));
    expect(toast()).toBeNull();
    vv.height = 800;
    await act(async () => listeners.forEach((l) => l()));
    expect(toast()).not.toBeNull();
  });

  it("the print toasts stack above it", async () => {
    // jsdom lays nothing out: the observer reports the toast's height as a browser would.
    vi.stubGlobal(
      "ResizeObserver",
      class {
        constructor(private readonly callback: ResizeObserverCallback) {}
        observe(target: Element) {
          this.callback([{ target, borderBoxSize: [{ blockSize: 88, inlineSize: 384 }], contentRect: { height: 88 } } as unknown as ResizeObserverEntry], this as unknown as ResizeObserver);
        }
        unobserve() {}
        disconnect() {}
      },
    );
    await showUpdate();
    const height = () => document.documentElement.style.getPropertyValue("--update-toast-h");
    expect(parseFloat(height())).toBeGreaterThan(0);
    const printToasts = screen.getByRole("region", { name: "Print status" });
    // Both offsets, the phone's (above the tab bar) and the desktop's, add the published height.
    expect(printToasts.className).toMatch(/(^|\s)bottom-\[calc\(\S*var\(--update-toast-h/);
    expect(printToasts.className).toMatch(/(^|\s)lg:bottom-\[calc\(\S*var\(--update-toast-h/);
    await userEvent.click(within(toast()!).getByRole("button", { name: "Later" }));
    expect(height()).toBe("0px");
  });

  it("everything goes after the version matches", async () => {
    await showUpdate();
    await act(async () => noteServerVersion(BUILT_FOR));
    expect(toast()).toBeNull();
    expect(sidebarReload()).toBeNull();
    expect(screen.queryByText(`${SERVER} ready`)).toBeNull();
  });
});
