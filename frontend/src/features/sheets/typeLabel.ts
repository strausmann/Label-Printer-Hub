// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { formatMm } from "./cellState";

/** The name the sheet list shows for a type, as the server builds it: "<vendor> <first product code>", else the code, else the key. */
export function typeLabel(type: { key: string; vendor: string | null; product_codes: string[] }): string {
  const code = type.product_codes[0];
  if (type.vendor && code) return `${type.vendor} ${code}`;
  return code ?? type.key;
}

/**
 * The readable name of a sheet type: "<vendor> <first product code> · <description>".
 * Without a vendor or a code only the description; without a description the short label; with nothing, the key.
 * Vendor and description can come from an imported file, so this is text for React to escape, never markup.
 */
export function typeTitle(type: { key: string; vendor: string | null; product_codes: string[]; description: string | null }): string {
  const label = typeLabel(type);
  const description = type.description?.trim();
  if (!description) return label;
  return type.vendor && type.product_codes[0] ? `${label} · ${description}` : description;
}

/** What a sheet type picker lists: label, key, label size and, for an archived type, that it is archived. */
export function typePickerLabel(
  type: { key: string; vendor: string | null; product_codes: string[]; description: string | null; archived_at?: string | null; geometry: { label_w: number; label_h: number } },
  locale: string,
  archivedWord: string,
): string {
  const width = formatMm(type.geometry.label_w, locale).replace(/ mm$/, "");
  return `${typeLabelWithKey(type)} · ${width} × ${formatMm(type.geometry.label_h, locale)}${type.archived_at ? ` · ${archivedWord}` : ""}`;
}

/** Label and key together, so two types with the same label can still be told apart. */
export function typeLabelWithKey(type: { key: string; vendor: string | null; product_codes: string[]; description: string | null }): string {
  const label = typeTitle(type);
  return label === type.key ? label : `${label} (${type.key})`;
}
