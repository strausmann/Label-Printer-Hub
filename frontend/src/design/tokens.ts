// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

/**
 * Design tokens (D3) as a typed object. This is the single source for the contrast test;
 * `tokens.test.ts` asserts that `tokens.css` carries exactly these values.
 * Values are fixed by the web-UI spec, section 5.2.
 */

/** Layer 1 — primitive values. */
export const primitives = {
  "paper-50": "#F6F4EF",
  "paper-100": "#EFEBE3",
  "paper-200": "#E3DED3",
  "paper-300": "#CFC8BA",
  "ink-900": "#1F1D1A",
  "ink-700": "#4A463F",
  // D12: #6B655A (was #777166, which reached only 4.40:1 on bg).
  "ink-500": "#6B655A",
  "amber-500": "#D4912A",
  "amber-600": "#B8771A",
  "amber-100": "#F6E6C8",
  "stamp-600": "#2F4E8F",
  "stamp-100": "#DDE5F3",
  "green-600": "#2E7A4E",
  "orange-600": "#B5651B",
  "red-600": "#B0352B",
} as const;

/** Layer 2 — semantic roles, resolved to hex for each theme. */
export interface Semantic {
  bg: string;
  surface: string;
  sunken: string;
  line: string;
  "line-strong": string;
  ink: string;
  "ink-2": string;
  "ink-3": string;
  accent: string;
  "accent-ink": string;
  "accent-soft": string;
  link: string;
  ok: string;
  warn: string;
  bad: string;
}

export const themes: { light: Semantic; dark: Semantic } = {
  light: {
    bg: primitives["paper-50"],
    surface: "#FDFCF9",
    sunken: primitives["paper-100"],
    line: primitives["paper-200"],
    "line-strong": primitives["paper-300"],
    ink: primitives["ink-900"],
    "ink-2": primitives["ink-700"],
    "ink-3": primitives["ink-500"],
    accent: primitives["amber-500"],
    "accent-ink": "#2B1D06",
    "accent-soft": primitives["amber-100"],
    link: primitives["stamp-600"],
    ok: primitives["green-600"],
    warn: primitives["orange-600"],
    bad: primitives["red-600"],
  },
  dark: {
    bg: "#171614",
    surface: "#201E1B",
    sunken: "#29261F",
    line: "#35312A",
    "line-strong": "#4A443A",
    ink: "#F1EEE7",
    "ink-2": "#C4BEB2",
    "ink-3": "#958E81",
    accent: "#E2A445",
    "accent-ink": "#241703",
    "accent-soft": "#3A2D16",
    link: "#8FAEE6",
    ok: "#6CC58F",
    warn: "#E39A4F",
    bad: "#EE8579",
  },
};

/** Tape colours describe the loaded material; they are never used for state. */
export const tape = {
  white: "#FFFFFF",
  yellow: "#F2D23C",
  green: "#5FAE5A",
  blue: "#3D78C9",
  red: "#D2473B",
} as const;

/** Radii 6 / 10 / 14 px (keys are the `--r-<key>` suffix). */
export const radii = { "1": "6px", "2": "10px", "3": "14px" } as const;

function luminance(hex: string): number {
  const channels = [1, 3, 5].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * channels[0]! + 0.7152 * channels[1]! + 0.0722 * channels[2]!;
}

/** WCAG 2.x contrast ratio between two `#RRGGBB` colours (1 … 21). */
export function contrastRatio(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi! + 0.05) / (lo! + 0.05);
}
