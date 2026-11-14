// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { afterEach, describe, expect, it, vi } from "vitest";
import { i18n } from "@lingui/core";
import { initI18n, pickLanguage, readStoredLanguage, storeLanguage, LANG_KEY } from "./index";
import { messages } from "./messages";

afterEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe("language order", () => {
  it("prefers the user's stored choice over the server default", () => {
    storeLanguage("de");
    expect(pickLanguage("en")).toBe("de");
  });

  it("uses the server default when nothing is stored", () => {
    expect(pickLanguage("de")).toBe("de");
  });

  it("falls back to en (D8)", () => {
    expect(pickLanguage(undefined)).toBe("en");
    localStorage.setItem(LANG_KEY, "fr");
    expect(pickLanguage("xx")).toBe("en");
  });

  it("survives a throwing localStorage", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(readStoredLanguage()).toBeNull();
    expect(() => storeLanguage("de")).not.toThrow();
    expect(pickLanguage("de")).toBe("de");
  });
});

describe("initI18n", () => {
  it("activates the requested locale with translated messages", async () => {
    await initI18n("de");
    expect(i18n.locale).toBe("de");
    const de = i18n._(messages.loading);
    await initI18n("en");
    expect(i18n.locale).toBe("en");
    const en = i18n._(messages.loading);
    expect(en).toBe("Loading…");
    expect(de).not.toBe(en);
  });
});
