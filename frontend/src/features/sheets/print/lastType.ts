// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

const key = (printerId: string) => `lph.sheetType.${printerId}`;

/**
 * The sheet type last used on a page printer (a per-browser convenience, like `lph.printer`).
 * It holds a type key only, nothing personal, so it stays on sign-out. Storage may be blocked or full.
 */
export const lastType = {
  get(printerId: string): string | null {
    try {
      return localStorage.getItem(key(printerId));
    } catch {
      return null;
    }
  },
  set(printerId: string, typeKey: string): void {
    try {
      localStorage.setItem(key(printerId), typeKey);
    } catch {
      /* not remembered */
    }
  },
};
