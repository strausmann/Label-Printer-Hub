import { render, screen } from "@testing-library/react";
import { I18nProvider } from "@lingui/react";
import { beforeEach, describe, expect, it } from "vitest";
import { i18n, initI18n } from "../../i18n";
import { MarkerSwatch, type Marker } from "./MarkerSwatch";

const marker = (over: Partial<Marker> = {}): Marker => ({
  name: "Black toner",
  color: "#000000",
  level_percent: 80,
  low: false,
  empty: false,
  some_remaining: false,
  type: "toner",
  ...over,
});
const ui = (m: Marker) => (
  <I18nProvider i18n={i18n}>
    <MarkerSwatch marker={m} />
  </I18nProvider>
);

describe("MarkerSwatch", () => {
  beforeEach(async () => {
    await initI18n("en");
  });

  it("says the level in words next to the name", () => {
    render(ui(marker()));
    expect(screen.getByText("Black toner")).toBeVisible();
    expect(screen.getByText("80 %")).toBeVisible();
  });

  it("a low marker at 0 % says so (spec 11.3)", () => {
    render(ui(marker({ name: "black", level_percent: 0, low: true })));
    expect(screen.getByText("black")).toBeVisible();
    expect(screen.getByText("0 %, low")).toBeVisible();
  });

  it("empty wins over a level", () => {
    render(ui(marker({ level_percent: 0, low: true, empty: true })));
    expect(screen.getByText("empty")).toBeVisible();
    expect(screen.queryByText(/%/)).toBeNull();
  });

  it("some remaining marker", () => {
    render(ui(marker({ level_percent: null, some_remaining: true })));
    expect(screen.getByText("some remaining")).toBeVisible();
  });

  it("a marker with nothing known says unknown", () => {
    render(ui(marker({ level_percent: null })));
    expect(screen.getByText("unknown")).toBeVisible();
  });

  it("the swatch is material: hidden from assistive technology, drawn only for a hex colour", () => {
    const { container, rerender } = render(ui(marker({ color: "#1e90ff" })));
    const swatch = container.querySelector("[data-swatch]") as HTMLElement;
    expect(swatch).toHaveAttribute("aria-hidden", "true");
    expect(swatch.style.backgroundColor).toBe("rgb(30, 144, 255)");
    // Anything that is not a plain hex colour is never written into a style.
    rerender(ui(marker({ color: "red; background:url(x)" })));
    expect((container.querySelector("[data-swatch]") as HTMLElement).style.backgroundColor).toBe("");
    rerender(ui(marker({ color: null })));
    expect((container.querySelector("[data-swatch]") as HTMLElement).style.backgroundColor).toBe("");
  });

  it("keeps a very long name inside its box", () => {
    const long = "Cyan high-yield toner cartridge with an extremely long supplier description ".repeat(3).trim();
    render(ui(marker({ name: long })));
    expect(screen.getByText(long).parentElement!.className).toContain("overflow-wrap:anywhere");
  });
});
