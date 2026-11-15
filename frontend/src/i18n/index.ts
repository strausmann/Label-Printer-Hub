// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { i18n, type Messages } from "@lingui/core";

export type Lang = "en" | "de";

export const LANGUAGES: readonly Lang[] = ["en", "de"];
/** Where the user's explicit language choice is remembered. */
export const LANG_KEY = "lph.lang";
/** D8: English is the default for a fresh install. */
export const DEFAULT_LANG: Lang = "en";

export function isLang(value: unknown): value is Lang {
  return value === "en" || value === "de";
}

export function readStoredLanguage(): Lang | null {
  try {
    const value = localStorage.getItem(LANG_KEY);
    return isLang(value) ? value : null;
  } catch {
    return null; // private window, blocked site data
  }
}

export function storeLanguage(lang: Lang): void {
  try {
    localStorage.setItem(LANG_KEY, lang);
  } catch {
    /* the choice then lasts for this page load only */
  }
}

/** Order: the user's choice → `/api/v1/info.default_language` → `en`. */
export function pickLanguage(serverDefault: string | undefined): Lang {
  return readStoredLanguage() ?? (isLang(serverDefault) ? serverDefault : DEFAULT_LANG);
}

const loaders: Record<Lang, () => Promise<{ messages: Messages }>> = {
  en: () => import("./locales/en/messages.po"),
  de: () => import("./locales/de/messages.po"),
};

export async function initI18n(lang: Lang): Promise<void> {
  const { messages } = await loaders[lang]();
  i18n.load(lang, messages);
  i18n.activate(lang);
  document.documentElement.lang = lang;
}

export { i18n };
