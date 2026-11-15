// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { mockApi } from "../features/test-api";
import { renderApp, SIGNED_IN } from "../test-utils";
import { navGroups } from "./features";

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
    expect(expected).toContain("calibration");
    for (const label of ["Overview", "Printers", "Jobs", "Sheets", "Sheet archive", "Calibration", "Paperless ASN", "Kept / Hangar / Grocy"]) {
      expect(names).toContain(label);
    }
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
});
