// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

export type ThemeChoice = "system" | "light" | "dark";

export const THEME_KEY = "lph.theme";
export const THEME_CHOICES: readonly ThemeChoice[] = ["system", "light", "dark"];

export function isTheme(value: unknown): value is ThemeChoice {
  return value === "system" || value === "light" || value === "dark";
}

export function readTheme(): ThemeChoice {
  try {
    const value = localStorage.getItem(THEME_KEY);
    return isTheme(value) ? value : "system";
  } catch {
    return "system"; // private window, blocked site data
  }
}

export function storeTheme(choice: ThemeChoice): void {
  try {
    localStorage.setItem(THEME_KEY, choice);
  } catch {
    /* the choice then lasts for this page load only */
  }
}

/** `system` removes the attribute so `prefers-color-scheme` decides (tokens.css). */
export function applyTheme(choice: ThemeChoice): void {
  const root = document.documentElement;
  if (choice === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", choice);
}
