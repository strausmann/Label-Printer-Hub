// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { renderHook } from "@testing-library/react";
import { I18nProvider } from "@lingui/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it } from "vitest";
import { i18n, initI18n } from "../../i18n";
import { isKnownReason, reasonWord, useReasonWord } from "./reasons";

const KEYWORDS = [
  "toner-empty",
  "toner-low",
  "media-empty",
  "media-jam",
  "door-open",
  "cover-open",
  "paused",
  "offline",
  "marker-supply-empty",
  "marker-supply-low",
  "media-low",
  "unknown-state",
  "not_accepting",
];

describe("reasonWord", () => {
  beforeEach(async () => {
    await initI18n("en");
  });

  it("gives words for every keyword of the list", () => {
    for (const keyword of KEYWORDS) {
      expect(isKnownReason(keyword), keyword).toBe(true);
    }
    // Words that are not the keyword itself (`paused` and `offline` read the same in English).
    for (const keyword of KEYWORDS.filter((k) => k !== "paused" && k !== "offline")) {
      expect(reasonWord(keyword, i18n._.bind(i18n)), keyword).not.toBe(keyword);
    }
    expect(reasonWord("toner-empty", i18n._.bind(i18n))).toBe("toner empty");
    expect(reasonWord("not_accepting", i18n._.bind(i18n))).toBe("not accepting jobs");
  });

  it("shows an unknown keyword verbatim", () => {
    expect(isKnownReason("developer-low")).toBe(false);
    expect(reasonWord("developer-low", i18n._.bind(i18n))).toBe("developer-low");
  });

  it("does not mistake an object property for a keyword", () => {
    expect(isKnownReason("constructor")).toBe(false);
    expect(reasonWord("constructor", i18n._.bind(i18n))).toBe("constructor");
    expect(reasonWord("__proto__", i18n._.bind(i18n))).toBe("__proto__");
  });

  it("translates through the active language", async () => {
    await initI18n("de");
    const wrapper = ({ children }: { children: ReactNode }) => <I18nProvider i18n={i18n}>{children}</I18nProvider>;
    const { result } = renderHook(() => useReasonWord(), { wrapper });
    expect(result.current("toner-empty")).toBe("Toner leer");
  });
});
