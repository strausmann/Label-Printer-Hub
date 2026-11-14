// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

/* Applies the stored theme choice before first paint (no flash). Mirrors src/shell/theme.ts;
   it is a separate file because the CSP allows scripts from this origin only (no inline script). */
try {
  var theme = localStorage.getItem("lph.theme");
  if (theme === "light" || theme === "dark") document.documentElement.setAttribute("data-theme", theme);
} catch {
  /* private window or blocked site data: follow the system */
}
