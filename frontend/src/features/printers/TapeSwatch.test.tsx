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
    render(ui({ tapeLoaded: null, probed: false }));
    expect(screen.getByText("Tape not known yet")).toBeVisible();
  });
  it("names an unknown colour without a swatch and says when none is reported", () => {
    const { unmount } = render(ui({ tapeLoaded: "9mm laminated clear/black" }));
    expect(screen.getByText("Clear")).toBeVisible();
    unmount();
    render(ui({ tapeLoaded: "12mm" }));
    expect(screen.getByText("Colour not reported")).toBeVisible();
  });
});
