import { render, screen } from "@testing-library/react";
import { I18nProvider } from "@lingui/react";
import { beforeEach, describe, expect, it } from "vitest";
import { i18n, initI18n } from "../../i18n";
import { TapeSwatch } from "./TapeSwatch";

beforeEach(async () => {
  await initI18n("en");
});
const ui = (props: Parameters<typeof TapeSwatch>[0]) => (
  <I18nProvider i18n={i18n}>
    <TapeSwatch {...props} />
  </I18nProvider>
);

describe("TapeSwatch", () => {
  it("does not claim an empty printer before the first probe", () => {
    render(ui({ widthMm: null, colour: null, probed: false }));
    expect(screen.getByText("Tape not known yet")).toBeVisible();
  });
  it("says the tape is not known, not that there is none, while the printer is offline", () => {
    render(ui({ widthMm: null, colour: null, probed: true, offline: true }));
    expect(screen.getByText("Tape not known")).toBeVisible();
    expect(screen.queryByText("No tape loaded")).toBeNull();
  });
  it("still says no tape for an online printer that reports none", () => {
    render(ui({ widthMm: null, colour: null, probed: true, offline: false }));
    expect(screen.getByText("No tape loaded")).toBeVisible();
  });
  it("shows no colour line without a colour", () => {
    render(ui({ widthMm: 12, colour: null }));
    expect(screen.getByText("12 mm")).toBeVisible();
    expect(screen.queryByText(/colour/i)).toBeNull();
  });
  it("names a colour next to its swatch", () => {
    render(ui({ widthMm: 12, colour: "clear" }));
    expect(screen.getByText("Clear")).toBeVisible();
  });
});
