import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderApp } from "../test-utils";

describe("Sidebar", () => {
  it("shows the entries of the shipped modules", async () => {
    await renderApp({ path: "/" });
    const nav = screen.getByRole("navigation", { name: "Main" });
    for (const name of ["Overview", "Printers", "Jobs", "Settings"]) {
      expect(within(nav).getByRole("link", { name })).toBeInTheDocument();
    }
  });

  it("hides entries whose feature is off", async () => {
    await renderApp({ path: "/", info: { features: { sheets: false, calibration: false, asn: false, kept: false } } });
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
});
