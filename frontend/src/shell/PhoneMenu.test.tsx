// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { MutationObserver } from "@tanstack/react-query";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type * as Actual from "./pullToRefresh";
import { afterEach, describe, expect, it, vi } from "vitest";
import { noteServerVersion, resetUpdatesForTest, setVersionCheckForTest } from "../app/updates";
import { mockApi } from "../features/test-api";
import { renderApp, SIGNED_IN } from "../test-utils";
import { navGroups } from "./features";
import { reloadApp } from "./pullToRefresh";

vi.mock("./pullToRefresh", async (importActual) => ({ ...(await importActual<typeof Actual>()), reloadApp: vi.fn() }));

const FEATURES = { sheets: true, calibration: true, asn: true, kept: true };
// With the sheet open the page behind it is hidden from assistive technology, the trigger included.
const trigger = () => screen.getByRole("button", { name: "Menu", hidden: true });
const open = async () => {
  await userEvent.click(trigger());
  return await screen.findByRole("dialog", { name: "Menu" });
};
const linkNames = (scope: HTMLElement) => within(scope).getAllByRole("link").map((l) => l.textContent);

describe("PhoneMenu", () => {
  it("the trigger is named Menu and reports collapsed, then expanded", async () => {
    mockApi({});
    await renderApp({ path: "/", info: { features: FEATURES } });
    expect(trigger()).toHaveAttribute("aria-expanded", "false");
    await open();
    expect(trigger()).toHaveAttribute("aria-expanded", "true");
  });

  it("an admin menu lists every sidebar entry and the six settings sections", async () => {
    mockApi({});
    await renderApp({ path: "/", info: { features: FEATURES } });
    const menu = await open();
    const names = linkNames(menu);
    // Every entry of the sidebar's own grouping (Settings opens as its sections), not a second list.
    const expected = navGroups({ isOn: (f) => FEATURES[f as keyof typeof FEATURES] ?? true, admin: true, integrations: [] })
      .flatMap((g) => g.entries)
      .map((e) => e.id)
      .filter((id) => id !== "settings");
    expect(expected).toEqual(["overview", "printers", "jobs", "sheets", "sheet-archive", "calibration", "asn", "kept"]);
    const labelOf: Record<string, string> = {
      overview: "Overview", printers: "Printers", jobs: "Jobs", sheets: "Sheets", "sheet-archive": "Sheet archive",
      calibration: "Calibration", asn: "Paperless ASN", kept: "Kept / Hangar / Grocy",
    };
    for (const id of expected) expect(names).toContain(labelOf[id]);
    expect(names).toEqual(expect.arrayContaining(["General", "Printers", "Integrations", "Access and keys", "Jobs", "System"]));
    expect(names.filter((n) => n === "Jobs")).toHaveLength(2);
  });

  it("a print session sees no settings entries", async () => {
    mockApi({});
    await renderApp({ path: "/", info: { features: FEATURES }, session: { ...SIGNED_IN, scope: "print" } });
    const menu = await open();
    const names = linkNames(menu);
    expect(names).not.toContain("General");
    expect(names).not.toContain("Access and keys");
    expect(within(menu).queryByText("Settings")).toBeNull();
    expect(names).toContain("Overview");
  });

  it("configured integrations are listed, others are not", async () => {
    mockApi({});
    await renderApp({
      path: "/",
      info: {
        integrations: [
          { name: "snipeit", configured: true },
          { name: "grocy", configured: false },
          { name: "spoolman", configured: true },
        ],
      },
    });
    const menu = await open();
    expect(within(menu).getByRole("link", { name: "Snipe-IT" })).toHaveAttribute("href", "/integrations/snipeit");
    expect(within(menu).getByRole("link", { name: "Spoolman" })).toBeInTheDocument();
    expect(within(menu).queryByRole("link", { name: "Grocy" })).toBeNull();
  });

  it("choosing an entry navigates and closes the menu", async () => {
    mockApi({});
    const { router } = await renderApp({ path: "/", info: { features: FEATURES } });
    const menu = await open();
    await userEvent.click(within(menu).getByRole("link", { name: "Calibration" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/calibration"));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Menu" })).toBeNull());
  });

  it("Escape closes and focus returns to the trigger", async () => {
    mockApi({});
    await renderApp({ path: "/" });
    await open();
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Menu" })).toBeNull());
    await waitFor(() => expect(trigger()).toHaveFocus());
  });

  it("the close button closes", async () => {
    mockApi({});
    await renderApp({ path: "/" });
    const menu = await open();
    await userEvent.click(within(menu).getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Menu" })).toBeNull());
  });

  it("About, the theme switch and Sign out are in the menu", async () => {
    mockApi({});
    await renderApp({ path: "/" });
    const menu = await open();
    expect(within(menu).getByRole("link", { name: "About and licences" })).toHaveAttribute("href", "/about");
    expect(within(menu).getByRole("button", { name: /^Theme:/ })).toBeInTheDocument();
    expect(within(menu).getByRole("button", { name: "Sign out" })).toBeInTheDocument();
  });

  it("the menu's last line shows the connection status with the running version", async () => {
    mockApi({});
    await renderApp({ path: "/", info: { version: "1.7.0" } });
    const menu = await open();
    const status = within(menu).getByText("Connected · v1.7.0");
    // The last line: nothing follows the status inside the sheet.
    expect(status.closest("div")!.lastElementChild).toContainElement(status);
  });

  it("the active page is marked", async () => {
    mockApi({});
    await renderApp({ path: "/jobs" });
    const menu = await open();
    const jobs = within(menu).getAllByRole("link", { name: "Jobs" });
    expect(jobs.some((l) => l.getAttribute("data-status") === "active")).toBe(true);
    const printers = within(menu).getAllByRole("link", { name: "Printers" });
    expect(printers.every((l) => l.getAttribute("data-status") !== "active")).toBe(true);
  });

  it.each([
    ["an integration link", "Grocy", "/integrations/grocy"],
    ["a settings link", "Access and keys", "/settings/access"],
    ["the About link", "About and licences", "/about"],
  ])("%s closes the menu", async (_what, name, path) => {
    mockApi({});
    const { router } = await renderApp({ path: "/", info: { features: FEATURES } });
    const menu = await open();
    await userEvent.click(within(menu).getByRole("link", { name }));
    await waitFor(() => expect(router.state.location.pathname).toBe(path));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Menu" })).toBeNull());
  });

  it("Reload reloads the app", async () => {
    mockApi({});
    vi.mocked(reloadApp).mockClear();
    await renderApp({ path: "/" });
    const menu = await open();
    const entry = within(menu).getByRole("button", { name: "Reload" });
    expect(entry).not.toHaveAttribute("aria-disabled");
    await userEvent.click(entry);
    expect(reloadApp).toHaveBeenCalledTimes(1);
  });

  it("Reload is disabled while a write is in flight", async () => {
    mockApi({});
    vi.mocked(reloadApp).mockClear();
    const { queryClient } = await renderApp({ path: "/" });
    const menu = await open();
    await act(async () => {
      void new MutationObserver(queryClient, { mutationFn: () => new Promise<void>(() => {}) }).mutate();
    });
    const entry = await within(menu).findByRole("button", { name: "Reload" });
    await waitFor(() => expect(entry).toHaveAttribute("aria-disabled", "true"));
    expect(entry).toHaveAccessibleDescription("Wait until the current action has finished.");
    await userEvent.click(entry);
    expect(reloadApp).not.toHaveBeenCalled();
  });

  it("Reload sits below the page entries inside the scrolling area", async () => {
    mockApi({});
    await renderApp({ path: "/" });
    const menu = await open();
    const scroll = within(menu).getByTestId("menu-scroll");
    expect(within(scroll).getByRole("button", { name: "Reload" })).toBeInTheDocument();
    const nav = within(scroll).getByRole("navigation", { name: "Pages" });
    expect(nav.compareDocumentPosition(within(scroll).getByRole("button", { name: "Reload" })) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("the menu shows the update box above the status line", async () => {
    setVersionCheckForTest({ buildVersion: "1.5.0", reload: vi.fn() });
    mockApi({});
    await renderApp({ path: "/", info: { version: "1.5.0" } });
    await act(async () => noteServerVersion("1.6.0"));
    const menu = await open();
    const reload = within(menu).getByRole("button", { name: "Reload new version" });
    expect(within(menu).getByText("1.6.0 ready")).toBeVisible();
    const status = within(menu).getByText("Connected · v1.5.0");
    expect(reload.compareDocumentPosition(status) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // The page entry keeps its own name: the two Reload buttons are told apart.
    expect(within(menu).getByRole("button", { name: "Reload" })).not.toBe(reload);
  });
});

afterEach(() => resetUpdatesForTest());
