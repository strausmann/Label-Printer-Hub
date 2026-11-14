// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { formatMm } from "./cellState";

/** The name the sheet list shows for a type, as the server builds it: "<vendor> <first product code>", else the code, else the key. */
export function typeLabel(type: { key: string; vendor: string | null; product_codes: string[] }): string {
  const code = type.product_codes[0];
  if (type.vendor && code) return `${type.vendor} ${code}`;
  return code ?? type.key;
}

/** What a sheet type picker lists: label, key, label size and, for an archived type, that it is archived. */
export function typePickerLabel(
  type: { key: string; vendor: string | null; product_codes: string[]; archived_at?: string | null; geometry: { label_w: number; label_h: number } },
  locale: string,
  archivedWord: string,
): string {
  const width = formatMm(type.geometry.label_w, locale).replace(/ mm$/, "");
  return `${typeLabelWithKey(type)} · ${width} × ${formatMm(type.geometry.label_h, locale)}${type.archived_at ? ` · ${archivedWord}` : ""}`;
}

/** Label and key together, so two types with the same label can still be told apart. */
export function typeLabelWithKey(type: { key: string; vendor: string | null; product_codes: string[] }): string {
  const label = typeLabel(type);
  return label === type.key ? label : `${label} (${type.key})`;
}
