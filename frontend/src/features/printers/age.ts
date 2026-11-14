// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

const UNITS: readonly [Intl.RelativeTimeFormatUnit, number][] = [
  ["day", 86_400],
  ["hour", 3_600],
  ["minute", 60],
  ["second", 1],
];

/** "143 days ago" / "vor 143 Tagen": the largest whole unit of seconds, minutes, hours and days, floored. */
export function formatAge(seconds: number, locale: string): string {
  const safe = Number.isFinite(seconds) ? Math.max(0, seconds) : 0;
  const [unit, size] = UNITS.find(([, s]) => safe >= s) ?? UNITS[UNITS.length - 1]!;
  return new Intl.RelativeTimeFormat(locale, { numeric: "always" }).format(-Math.floor(safe / size), unit);
}
