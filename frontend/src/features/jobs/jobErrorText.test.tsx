// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { i18n } from "@lingui/core";
import { I18nProvider } from "@lingui/react";
import { renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { initI18n } from "../../i18n";
import { useJobErrorText, useStoredJobErrorText } from "./jobErrorText";

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

  it("R26-2: a label longer than the tape allows has its own words, en and de", async () => {
    expect(await storedFor("label_too_long: The label is 1601 mm long", { length_mm: 1601, max_mm: 1000 }, "en")).toBe(
      "This label is 1601 mm long; this tape holds at most 1000 mm. Shorten the text.",
    );
    expect(await storedFor("label_too_long: The label is 1601 mm long", { length_mm: 1601, max_mm: 1000 }, "de")).toBe(
      "Dieses Etikett ist 1601 mm lang, dieses Band erlaubt höchstens 1000 mm. Kürze den Text.",
    );
  });

  it("an unknown code still names the code", async () => {
    expect(await textFor("no_such_code", "en")).toBe("The print failed (error code no_such_code).");
  });
});

async function storedFor(error: string | null, detail: Record<string, unknown> | null, lang: "en" | "de") {
  await initI18n(lang);
  const { result } = renderHook(() => useStoredJobErrorText(), {
    wrapper: ({ children }) => <I18nProvider i18n={i18n}>{children}</I18nProvider>,
  });
  return result.current(error, detail);
}

describe("a job's stored error in the app's words (#389)", () => {
  it("translates every known code, en and de", async () => {
    expect(await storedFor("tape_empty: The tape is empty.", null, "en")).toBe("The tape is empty. Put in a new tape and retry.");
    const de = await storedFor("tape_empty: The tape is empty.", null, "de");
    expect(de).not.toBe("The tape is empty. Put in a new tape and retry.");
    expect(de).not.toMatch(/tape_empty/);
  });

  it("falls back to the print error words for a code only a refusal knows", async () => {
    expect(await storedFor("no_tape_loaded: No tape loaded", null, "en")).toBe("No tape is loaded. Put in a tape and try again.");
  });

  it("names the reported flags of a printer error", async () => {
    expect(await storedFor("printer_error: The printer reports an error: jammed, offline", { flags: ["jammed", "offline"] }, "en")).toBe(
      "The printer reports: Tape jammed — clear it to print · The printer reports itself offline. Fix it on the printer and retry.",
    );
  });

  it("keeps the stored text of an unknown code or a message without a code", async () => {
    expect(await storedFor("weird_code: something odd", null, "en")).toBe("weird_code: something odd");
    expect(await storedFor("Printer reported: cover open", null, "en")).toBe("Printer reported: cover open");
    expect(await storedFor(null, null, "en")).toBeNull();
  });
});
