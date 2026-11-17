// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { i18n } from "@lingui/core";
import { I18nProvider } from "@lingui/react";
import { renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { initI18n } from "../../i18n";
import { useJobErrorText } from "./jobErrorText";

async function textFor(code: string | null, lang: "en" | "de") {
  await initI18n(lang);
  const { result } = renderHook(() => useJobErrorText(), {
    wrapper: ({ children }) => <I18nProvider i18n={i18n}>{children}</I18nProvider>,
  });
  return result.current(code);
}

describe("job error words", () => {
  it("a page job past the render time limit has its own words (#293), en and de", async () => {
    expect(await textFor("render_timeout", "en")).toBe("Drawing the page took too long.");
    expect(await textFor("render_timeout", "de")).toBe("Das Rendern der Seite hat zu lange gedauert.");
  });

  it("a page job without a free render slot has its own words (#293), en and de", async () => {
    expect(await textFor("render_unavailable", "en")).toBe(
      "No drawing slot became free in time; the page was not drawn. Try again later.",
    );
    expect(await textFor("render_unavailable", "de")).toBe(
      "Es wurde nicht rechtzeitig ein Platz zum Rendern frei, die Seite wurde nicht gerendert. Versuch es später noch einmal.",
    );
  });

  it("#389: a die-cut roll and an error the printer reports after sending have their own words, en and de", async () => {
    expect(await textFor("media_type_mismatch", "en")).toBe(
      "The loaded roll is die-cut labels. The hub prints on continuous tape only; put in a continuous roll and retry.",
    );
    expect(await textFor("printer_error", "en")).toBe(
      "The printer reported an error after the label was sent. Check the printer's display, fix it and retry.",
    );
    expect(await textFor("media_type_mismatch", "de")).not.toMatch(/die-cut/);
    expect(await textFor("printer_error", "de")).not.toMatch(/The printer/);
  });

  it("an unknown code still names the code", async () => {
    expect(await textFor("no_such_code", "en")).toBe("The print failed (error code no_such_code).");
  });
});
