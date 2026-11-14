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
/** The sheet type of the default target; read only when its printer is a page printer (R-281-13). */
export const GROCY_LABEL_DEFAULT_SHEET_TYPE_KEY = "integrations.grocy.label.sheet_type";
/** The sheet type of a type's own target; read only when that type has its own page printer. */
export const grocySheetTypeKey = (type: GrocyLabelType) => `integrations.grocy.label.${type}.sheet_type`;

/** A target: the default (`"default"`) or the override of one label type. */
export type GrocyTarget = "default" | GrocyLabelType;
const printerKeyOf = (target: GrocyTarget) => (target === "default" ? GROCY_LABEL_DEFAULT_PRINTER_KEY : grocyPrinterKey(target));
const sheetTypeKeyOf = (target: GrocyTarget) => (target === "default" ? GROCY_LABEL_DEFAULT_SHEET_TYPE_KEY : grocySheetTypeKey(target));

export const grocyLabelKeys = (): string[] => [
  GROCY_LABEL_ENABLED_KEY,
  GROCY_LABEL_DEFAULT_PRINTER_KEY,
  GROCY_LABEL_DEFAULT_SHEET_TYPE_KEY,
  ...GROCY_LABEL_TYPES.flatMap((type) => [grocyContentTypeKey(type), grocyPrinterKey(type), grocySheetTypeKey(type)]),
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

export const isPagePrinter = (printer: LabelPrinter | undefined): boolean => printer?.backend === "ipp";

export interface LabelPrinterOption {
  id: string;
  label: string;
  /** The group the option is listed under; the empty choice and an unavailable slug have none. */
  section?: string;
}

/**
 * The printers a label can go to: the empty choice first, then the enabled tape printers and the enabled page printers,
 * each under its group (R-281-18). A saved slug that is not among them (disabled, removed) stays in the list under
 * `unavailable(slug)`, so the select still shows what is stored instead of jumping to another printer. `printers` is
 * `null` while the list is not known (loading, or the request failed): then the saved slug is shown as it is, because
 * nothing says it is unavailable.
 */
export function labelPrinterOptions(
  printers: readonly LabelPrinter[] | null,
  current: string,
  emptyLabel: string,
  unavailable: (slug: string) => string,
  groups: { tape: string; page: string },
): LabelPrinterOption[] {
  const enabled = (printers ?? []).filter((p) => p.enabled);
  const usable: LabelPrinterOption[] = [
    ...enabled.filter((p) => !isPagePrinter(p)).map((p) => ({ id: p.slug, label: p.name, section: groups.tape })),
    ...enabled.filter(isPagePrinter).map((p) => ({ id: p.slug, label: p.name, section: groups.page })),
  ];
  const options: LabelPrinterOption[] = [{ id: "", label: emptyLabel }, ...usable];
  if (current !== "" && !usable.some((o) => o.id === current)) {
    options.push({ id: current, label: printers === null ? current : unavailable(current) });
  }
  return options;
}

/** The saved or edited values of the label keys, by key (only the keys that matter here are read). */
export type GrocyLabelDraft = Readonly<Record<string, unknown>>;

export type GrocyTargetIssue = "sheet_type_required" | "sheet_type_unavailable";

/** What the sheet type picker needs of a sheet type. */
export interface LabelSheetType {
  key: string;
  archived_at: string | null;
}

/**
 * What is wrong with the sheet type of each target whose printer is a page printer: none chosen
 * (`sheet_type_required`, the save is blocked) or one that is archived or gone (`sheet_type_unavailable`, the hub
 * refuses those labels). A tape printer, the default target of a type and an unknown printer list have nothing to
 * say. `types` is `null` while the sheet types are not known: then only a missing type is flagged.
 */
export function grocyTargetIssues(
  draft: GrocyLabelDraft,
  printers: readonly LabelPrinter[] | null,
  types: readonly LabelSheetType[] | null,
): Partial<Record<GrocyTarget, GrocyTargetIssue>> {
  const issues: Partial<Record<GrocyTarget, GrocyTargetIssue>> = {};
  for (const target of ["default", ...GROCY_LABEL_TYPES] as const) {
    const slug = String(draft[printerKeyOf(target)] ?? "");
    if (slug === "" || !isPagePrinter(printers?.find((p) => p.slug === slug))) continue;
    const key = String(draft[sheetTypeKeyOf(target)] ?? "");
    if (key === "") issues[target] = "sheet_type_required";
    else if (types !== null && !types.some((t) => t.key === key && t.archived_at === null)) issues[target] = "sheet_type_unavailable";
  }
  return issues;
}

/**
 * The keys to set when a target's printer changes: the printer, and an emptied sheet type when the new printer is no
 * page printer (a tape printer, or "Same as default" / the first tape printer). A page printer keeps the sheet type.
 */
export function grocyLabelChanges(target: GrocyTarget, slug: string, printers: readonly LabelPrinter[] | null): Record<string, string> {
  const changes: Record<string, string> = { [printerKeyOf(target)]: slug };
  if (slug === "" || !isPagePrinter(printers?.find((p) => p.slug === slug))) changes[sheetTypeKeyOf(target)] = "";
  return changes;
}
