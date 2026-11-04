import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderApp, SIGNED_IN } from "../test-utils";

describe("Sidebar", () => {
  it("shows the entries of the shipped modules", async () => {
    await renderApp({ path: "/" });
    const nav = screen.getByRole("navigation", { name: "Main" });
    for (const name of ["Overview", "Printers", "Jobs", "Settings"]) {
      expect(within(nav).getByRole("link", { name })).toBeInTheDocument();
    }
  });

  it("hides entries whose feature is off", async () => {
    await renderApp({ path: "/", info: { integrations: [], features: { sheets: false, calibration: false, asn: false, kept: false } } });
    const nav = screen.getByRole("navigation", { name: "Main" });
    for (const name of ["Sheets", "Sheet archive", "Calibration", "Paperless ASN", "Kept / Hangar / Grocy"]) {
      expect(within(nav).queryByRole("link", { name })).toBeNull();
    }
    // A group whose entries are all hidden shows no heading either.
    expect(within(nav).queryByText("Material")).toBeNull();
    expect(within(nav).queryByText("Integrations")).toBeNull();
  });

  it("shows an entry as soon as its feature is on", async () => {
    await renderApp({ path: "/", info: { features: { sheets: true, asn: true } } });
    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(within(nav).getByRole("link", { name: "Sheets" })).toBeInTheDocument();
    expect(within(nav).getByRole("link", { name: "Paperless ASN" })).toBeInTheDocument();
    expect(within(nav).getByText("Material")).toBeInTheDocument();
    expect(within(nav).queryByRole("link", { name: "Calibration" })).toBeNull();
  });

  it("marks the current page", async () => {
    await renderApp({ path: "/jobs" });
    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(within(nav).getByRole("link", { name: "Jobs" })).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByRole("link", { name: "Printers" })).not.toHaveAttribute("aria-current");
  });

  describe("integrations group", () => {
    const set = (snipeit: boolean, grocy: boolean, spoolman: boolean) => [
      { name: "snipeit" as const, configured: snipeit },
      { name: "grocy" as const, configured: grocy },
      { name: "spoolman" as const, configured: spoolman },
    ];

    it("lists a link per configured integration under the heading", async () => {
      await renderApp({ path: "/", info: { integrations: set(true, true, false) } });
      const nav = screen.getByRole("navigation", { name: "Main" });
      const group = within(nav).getByRole("list", { name: "Integrations" });
      expect(within(group).getByRole("link", { name: "Snipe-IT" })).toHaveAttribute("href", "/integrations/snipeit");
      expect(within(group).getByRole("link", { name: "Grocy" })).toHaveAttribute("href", "/integrations/grocy");
    });

    it("an admin sees a muted entry for an integration that is not set up, linking to the settings", async () => {
      await renderApp({ path: "/", info: { integrations: set(true, true, false) } });
      const nav = screen.getByRole("navigation", { name: "Main" });
      const link = within(nav).getByRole("link", { name: /Spoolman/ });
      expect(link).toHaveAttribute("href", "/settings/integrations");
      expect(link).toHaveTextContent("Not set up");
    });

    it("a non-admin does not see it at all", async () => {
      await renderApp({ path: "/", info: { integrations: set(true, true, false) }, session: { ...SIGNED_IN, scope: "print" } });
      const nav = screen.getByRole("navigation", { name: "Main" });
      expect(within(nav).queryByText(/Spoolman/)).toBeNull();
      expect(within(nav).getByRole("link", { name: "Snipe-IT" })).toBeVisible();
    });

    it("only configured integrations are linked to their start page", async () => {
      await renderApp({ path: "/", info: { integrations: set(false, false, false) } });
      const nav = screen.getByRole("navigation", { name: "Main" });
      expect(within(nav).queryByRole("link", { name: "Snipe-IT" })).toBeNull();
      expect(within(nav).getAllByRole("link", { name: /Not set up/ })).toHaveLength(3);
    });

    it("marks the open start page", async () => {
      await renderApp({ path: "/integrations/grocy" });
      const nav = screen.getByRole("navigation", { name: "Main" });
      expect(within(nav).getByRole("link", { name: "Grocy" })).toHaveAttribute("aria-current", "page");
    });
  });
});
