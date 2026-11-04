import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderApp } from "../test-utils";

function labels(nav: HTMLElement): string[] {
  return within(nav)
    .getAllByRole("link")
    .map((a) => a.textContent ?? "");
}

describe("TabBar", () => {
  it("lists Overview, Printers, Scan, Jobs and hides Sheets while the feature is off", async () => {
    await renderApp();
    const nav = screen.getByRole("navigation", { name: "Tabs" });
    expect(labels(nav)).toEqual(["Overview", "Printers", "Scan", "Jobs"]);
  });

  it("adds Sheets as the last tab when the feature is on", async () => {
    await renderApp({ info: { features: { sheets: true } } });
    expect(labels(screen.getByRole("navigation", { name: "Tabs" }))).toEqual(["Overview", "Printers", "Scan", "Jobs", "Sheets"]);
  });

  it("keeps Scan in the centre slot of five whether or not Sheets is shown", async () => {
    for (const sheets of [false, true]) {
      const { unmount } = await renderApp({ info: { features: { sheets } } });
      const slots = Array.from(screen.getByRole("navigation", { name: "Tabs" }).children);
      expect(slots).toHaveLength(5);
      expect(slots[2]).toHaveTextContent("Scan");
      unmount();
    }
  });
});
