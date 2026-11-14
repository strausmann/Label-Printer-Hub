// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

/** The settings behind Grocy's label printer webhook (#281, R-281-7), in the registry's order. */

export const GROCY_LABEL_TYPES = ["product", "stock_entry", "chore", "battery", "recipe"] as const;
export type GrocyLabelType = (typeof GROCY_LABEL_TYPES)[number];

export const GROCY_LABEL_ENABLED_KEY = "integrations.grocy.label.enabled";
/** The default target; `""` is the first enabled tape printer. */
export const GROCY_LABEL_DEFAULT_PRINTER_KEY = "integrations.grocy.label.printer";
export const grocyContentTypeKey = (type: GrocyLabelType) => `integrations.grocy.label.${type}.content_type`;
/** A type's own target; `""` is the default target. */
export const grocyPrinterKey = (type: GrocyLabelType) => `integrations.grocy.label.${type}.printer`;

export const grocyLabelKeys = (): string[] => [
  GROCY_LABEL_ENABLED_KEY,
  GROCY_LABEL_DEFAULT_PRINTER_KEY,
  ...GROCY_LABEL_TYPES.flatMap((type) => [grocyContentTypeKey(type), grocyPrinterKey(type)]),
];

/** The four lines for Grocy's `config.php` (R-281-9). The key stays a placeholder: it is never shown again after it was created. */
export function grocyConfigBlock(publicUrl: string): string {
  const base = publicUrl.trim().replace(/\/+$/, "") || "<public-url>";
  return [
    "Setting('FEATURE_FLAG_LABEL_PRINTER', true);",
    `Setting('LABEL_PRINTER_WEBHOOK', '${base}/api/v1/webhook/grocy/label?token=<print-key>');`,
    "Setting('LABEL_PRINTER_RUN_SERVER', true);",
    "Setting('LABEL_PRINTER_HOOK_JSON', true);",
  ].join("\n");
}

export interface LabelPrinter {
  slug: string;
  name: string;
  backend: string;
  enabled: boolean;
}

/**
 * The printers a label can go to: the empty choice first, then the enabled tape printers. A saved slug that is
 * not among them (disabled, removed, a page printer) stays in the list under `unavailable(slug)`, so the select
 * still shows what is stored instead of jumping to another printer.
 */
export function labelPrinterOptions(
  printers: readonly LabelPrinter[],
  current: string,
  emptyLabel: string,
  unavailable: (slug: string) => string,
): { id: string; label: string }[] {
  const usable = printers.filter((p) => p.enabled && p.backend !== "ipp").map((p) => ({ id: p.slug, label: p.name }));
  const options = [{ id: "", label: emptyLabel }, ...usable];
  if (current !== "" && !usable.some((o) => o.id === current)) options.push({ id: current, label: unavailable(current) });
  return options;
}
