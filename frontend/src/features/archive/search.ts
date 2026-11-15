// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

/** The address of the archive page: filters of the list, and the type that is open. */
export interface ArchiveSearch {
  q?: string | undefined;
  page?: "A4" | "Letter" | undefined;
  vendor?: string | undefined;
  /** Label width in mm. */
  w?: number | undefined;
  /** Label height in mm. */
  h?: number | undefined;
  archived?: true | undefined;
  /** The key of the open type. */
  type?: string | undefined;
}

/** What the API accepts (`GET /api/v1/sheet-types`): longer values answer 422. */
export const MAX_QUERY = 100;
export const MAX_VENDOR = 200;

// The router parses `?q=123` as the number 123, so text arrives as a string or a number.
const text = (value: unknown): string | undefined => {
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return typeof value === "string" && value.trim() !== "" ? value : undefined;
};

const size = (value: unknown): number | undefined => {
  const n = typeof value === "number" ? value : typeof value === "string" ? Number(value) : NaN;
  return Number.isFinite(n) && n > 0 && n <= 1000 ? n : undefined;
};

/** Every key stays in the result even when rejected: the router merges it over the raw query string. */
export function parseArchiveSearch(search: Record<string, unknown>): ArchiveSearch {
  const page = text(search.page);
  return {
    q: text(search.q)?.slice(0, MAX_QUERY),
    page: page === "A4" || page === "Letter" ? page : undefined,
    vendor: text(search.vendor)?.slice(0, MAX_VENDOR),
    w: size(search.w),
    h: size(search.h),
    archived: search.archived === true || search.archived === "true" || search.archived === 1 ? true : undefined,
    type: text(search.type),
  };
}

/** A decimal typed by a person ("45,7" or "45.7"); null when it is not a number. */
export function parseDecimal(value: string): number | null {
  const trimmed = value.trim().replace(",", ".");
  if (trimmed === "") return null;
  const n = Number(trimmed);
  return Number.isFinite(n) ? n : null;
}

/** A source address worth a link: only http and https. */
export function httpUrl(value: string | null | undefined): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:" ? value : null;
  } catch {
    return null;
  }
}
