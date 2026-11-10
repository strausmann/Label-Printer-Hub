import type { SheetTypeRead, VersionRead } from "./api";

/**
 * The pre-filled issue behind "Report a problem with the dimensions" and "Confirm the dimensions" (#230).
 *
 * Privacy by construction: the builder takes a `FeedbackInput` and reads exactly the fields named below.
 * There is no parameter for a host, a printer address, an API key, a user name, a sheet code or an
 * integration URL, so none of them can travel; nothing is read from the page.
 */

/** The ids of the issue form (`.github/ISSUE_TEMPLATE/sheet-type-feedback.yml`), in its order. */
export const FEEDBACK_FIELD_IDS = [
  "kind",
  "type_key",
  "type_version",
  "version_note",
  "vendor",
  "product_codes",
  "geometry",
  "allow_qr",
  "verified",
  "provenance",
  "printer_model",
  "tray",
  "calibration",
  "observed",
  "hub_version",
  "scheme",
  "browser",
  "privacy_check",
] as const;

export type FeedbackFieldId = (typeof FEEDBACK_FIELD_IDS)[number];
export type FeedbackKind = "wrong" | "confirmed";

export interface FeedbackInput {
  kind: FeedbackKind;
  sheetType: SheetTypeRead;
  version: VersionRead;
  hubVersion: string;
  scheme: "http" | "https";
  printer?: { model: string; tray: string; calibration: "calibrated" | "uncalibrated" };
  browser?: string;
}

export const FEEDBACK_BASE = "https://github.com/strausmann/Label-Printer-Hub/issues/new?template=sheet-type-feedback.yml";

/** Longer addresses are cut off by GitHub (or by proxies on the way). */
export const MAX_URL = 8000;

/** The words of the form's dropdowns: a pre-filled value must match an option exactly. */
const KIND_TEXT: Record<FeedbackKind, string> = { wrong: "Dimensions are wrong", confirmed: "Dimensions are confirmed" };
const KIND_TITLE: Record<FeedbackKind, string> = { wrong: "dimensions wrong", confirmed: "dimensions confirmed" };
const KIND_LABELS: Record<FeedbackKind, string> = { wrong: "area:sheets,type:bug", confirmed: "area:sheets,type:feedback" };

/** Every stored number of a version, one per line: `name: value mm` (counts and the page size without unit). */
const GEOMETRY_FIELDS = [
  ["page_size", ""],
  ["shape", ""],
  ["cols", ""],
  ["rows", ""],
  ["label_w", " mm"],
  ["label_h", " mm"],
  ["pitch_x", " mm"],
  ["pitch_y", " mm"],
  ["margin_top", " mm"],
  ["margin_left", " mm"],
  ["corner_radius", " mm"],
  ["page_w", " mm"],
  ["page_h", " mm"],
] as const;

function geometryText(version: VersionRead): string {
  const stored = version.geometry as Record<string, string | number | null | undefined>;
  return GEOMETRY_FIELDS.flatMap(([name, unit]) => {
    const value = stored[name];
    return value === null || value === undefined ? [] : [`${name}: ${value}${unit}`];
  }).join("\n");
}

/**
 * The source name always; its URL only for a type that shipped with the hub. For `custom` and `imported`
 * types the URL was typed in by a user and may point into an intranet.
 */
function provenanceText(type: SheetTypeRead): string {
  const name = type.source_name ?? "";
  const url = type.origin === "seed" ? (type.source_url ?? "") : "";
  return [name, url].filter(Boolean).join("\n");
}

/** "Firefox 140": family and major version only, never the full user-agent string. */
export function browserLabel(userAgent: string): string | undefined {
  const rules: [RegExp, string][] = [
    [/\bEdg\/(\d+)/, "Edge"],
    [/\bFirefox\/(\d+)/, "Firefox"],
    [/\bChrome\/(\d+)/, "Chrome"],
    [/\bVersion\/(\d+)[^]*\bSafari\//, "Safari"],
  ];
  for (const [pattern, name] of rules) {
    const match = pattern.exec(userAgent);
    if (match) return `${name} ${match[1]}`;
  }
  return undefined;
}

const exportPointer = (key: string) => `See the export: /api/v1/sheet-types/${key}/export (paste it here)`;

type Fields = Partial<Record<FeedbackFieldId | "title" | "labels", string>>;

const without = (fields: Fields, names: (keyof Fields)[]): Fields =>
  Object.fromEntries(Object.entries(fields).filter(([name]) => !names.includes(name as keyof Fields)));

function serialize(fields: Fields): string {
  const query = new URLSearchParams();
  for (const name of ["title", "labels", ...FEEDBACK_FIELD_IDS] as const) {
    const value = fields[name];
    if (value) query.set(name, value);
  }
  return `${FEEDBACK_BASE}&${query.toString()}`;
}

/** Keeps the first product codes that fit and says how many are left out. */
function trimCodes(fields: Fields, codes: string[]): Fields {
  let kept = codes.length;
  while (kept > 0) {
    kept -= 1;
    const next = { ...fields, product_codes: [...codes.slice(0, kept), `… and ${codes.length - kept} more (see the export)`].join("\n") };
    if (serialize(next).length <= MAX_URL) return next;
  }
  return { ...fields, product_codes: `${codes.length} product codes (see the export)` };
}

export function buildFeedbackUrl(input: FeedbackInput): string {
  const { kind, sheetType: type, version, printer } = input;
  const full: Fields = {
    title: `[sheet type] ${type.key} v${version.version}: ${KIND_TITLE[kind]}`,
    labels: KIND_LABELS[kind],
    kind: KIND_TEXT[kind],
    type_key: type.key,
    type_version: String(version.version),
    version_note: version.change_note ?? undefined,
    vendor: type.vendor ?? undefined,
    product_codes: type.product_codes.join("\n"),
    geometry: geometryText(version),
    allow_qr: type.allow_qr ? "allowed" : "not allowed",
    verified: type.verified ? "yes" : "no",
    provenance: provenanceText(type),
    printer_model: printer?.model,
    tray: printer?.tray,
    calibration: printer?.calibration,
    hub_version: input.hubVersion,
    scheme: input.scheme,
    browser: input.browser,
  };

  // What gives way first, in this order, until the address fits.
  const steps: ((f: Fields) => Fields)[] = [
    (f) => without(f, ["browser"]),
    (f) => without(f, ["printer_model", "tray", "calibration"]),
    (f) => without(f, ["version_note"]),
    (f) => ({ ...f, provenance: type.source_name ?? undefined }),
    (f) => ({ ...f, geometry: exportPointer(type.key) }),
  ];
  let fields = full;
  for (const step of steps) {
    if (serialize(fields).length <= MAX_URL) return serialize(fields);
    fields = step(fields);
  }
  // Last resort, beyond the documented steps: a type with long codes can still be too long.
  return serialize(serialize(fields).length <= MAX_URL ? fields : trimCodes(fields, type.product_codes));
}
