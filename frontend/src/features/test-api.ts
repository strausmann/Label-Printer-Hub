// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { vi } from "vitest";
import type { components } from "../api/schema.gen";

export const PRINTER_A = {
  id: "11111111-1111-4111-8111-111111111111",
  name: "Workshop PT-P750W",
  slug: "workshop-pt",
  model: "PT-P750W",
  backend: "ptouch",
  connection: { host: "192.0.2.10", port: 9100 },
  enabled: true,
  paused: false,
  created_at: "2026-11-01T08:00:00Z",
  updated_at: "2026-11-01T08:00:00Z",
};
export const PRINTER_B = {
  ...PRINTER_A,
  id: "22222222-2222-4222-8222-222222222222",
  name: "Office QL-820NWB",
  slug: "office-ql",
  model: "QL-820NWB",
  backend: "brother_ql",
  connection: { host: "Printer-B.Example.invalid", port: 9100 },
  paused: true,
};

export const status = (printerId: string, over: Record<string, unknown> = {}) => ({
  printer_id: printerId,
  online: true,
  captured_at: "2026-11-04T10:00:00Z",
  error_state: null,
  last_error: null,
  last_probe_age_s: 4,
  stale: false,
  polled: true,
  identity_mismatch: false,
  roll_prompt: false,
  note: null,
  tape_loaded: "12mm laminated",
  tape_width_mm: 12,
  tape_colour: "blue" as const,
  ...over,
});

export const job = (id: string, printerId: string, state: string, over: Record<string, unknown> = {}) => ({
  id,
  printer_id: printerId,
  template_key: "asset-label",
  state,
  payload: {},
  result: null,
  error: null,
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
  started_at: null,
  finished_at: null,
  ...over,
});

/** A handler gets the request and its URL, so a route can honour the query string the way the server does. */
type Handler = (init: RequestInit, url: URL) => unknown;

/** A non-200 JSON answer for a mocked route (return it from a handler or use it as the route value). */
export const respond = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

/** A PNG answer (a few bytes are enough: nothing decodes them in jsdom). */
export const pngResponse = () => new Response(new Uint8Array([137, 80, 78, 71]), { status: 200, headers: { "Content-Type": "image/png" } });
export interface Call {
  method: string;
  path: string;
  search: string;
  headers: Headers;
  body: string | undefined;
}

/**
 * Stubs `fetch` for one test. Keys are `"METHOD /path"`; a handler's return value is the JSON
 * body (`null` answers 204). Unlisted routes answer 404, so a forgotten route fails loudly.
 */
export function mockApi(routes: Record<string, Handler | unknown>) {
  const calls: Call[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = new URL(String(input), "http://localhost");
    const method = (init.method ?? "GET").toUpperCase();
    calls.push({ method, path: url.pathname, search: url.search, headers: new Headers(init.headers), body: typeof init.body === "string" ? init.body : undefined });
    const route = routes[`${method} ${url.pathname}`];
    if (route === undefined) {
      return new Response(JSON.stringify({ detail: "not mocked" }), { status: 404, headers: { "Content-Type": "application/json" } });
    }
    const body = typeof route === "function" ? await (route as Handler)(init, url) : route;
    if (body instanceof Response) return body;
    if (body === null) return new Response(null, { status: 204 });
    return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
  });
  vi.stubGlobal("fetch", fetchMock);
  return { calls, fetchMock };
}

type SettingKind = "str" | "int" | "float" | "bool" | "url" | "secret" | "enum";
export interface SettingFixture {
  key: string;
  kind: SettingKind;
  value?: unknown;
  is_set: boolean;
  locked: boolean;
  state: "ok" | "undecryptable" | "env_secret_needs_env_url";
  choices: string[];
}

/** One `SettingView` as `GET /api/v1/settings` answers it. */
export const settingView = (key: string, kind: SettingKind, over: Partial<SettingFixture> = {}): SettingFixture => ({
  key,
  kind,
  value: kind === "secret" ? null : "",
  is_set: false,
  locked: false,
  state: "ok",
  choices: [],
  ...over,
});

/** The full list the registry produces, with obviously fake values. */
export const settingsList = (over: Record<string, Partial<SettingFixture>> = {}): SettingFixture[] =>
  [
    settingView("general.display_name", "str", { value: "Labelyard", is_set: true }),
    settingView("general.language", "enum", { value: "en", choices: ["en", "de"] }),
    settingView("general.time_zone", "str", { value: "UTC" }),
    settingView("general.public_url", "url", { value: "https://hub.example.invalid", is_set: true, locked: true }),
    settingView("integrations.snipeit.url", "url", { value: "https://assets.example.invalid", is_set: true }),
    settingView("integrations.snipeit.api_key", "secret", { is_set: true }),
    settingView("integrations.snipeit.timeout", "float", { value: 5 }),
    settingView("integrations.grocy.url", "url", { value: "" }),
    settingView("integrations.grocy.api_key", "secret"),
    settingView("integrations.grocy.timeout", "float", { value: 5 }),
    settingView("integrations.grocy.label.enabled", "bool", { value: false }),
    settingView("integrations.grocy.label.printer", "str", { value: "" }),
    ...(["product", "stock_entry", "chore", "battery", "recipe"] as const).flatMap((type) => [
      settingView(`integrations.grocy.label.${type}.content_type`, "enum", {
        value: type === "stock_entry" ? "qr_three_lines" : "qr_two_lines",
        choices: ["qr_only", "qr_one_line", "qr_two_lines", "qr_three_lines"],
      }),
      settingView(`integrations.grocy.label.${type}.printer`, "str", { value: "" }),
    ]),
    settingView("integrations.spoolman.url", "url", { value: "" }),
    settingView("integrations.spoolman.timeout", "float", { value: 5 }),
    settingView("integrations.paperless.url", "url", { value: "" }),
    settingView("integrations.paperless.token", "secret"),
    settingView("integrations.paperless.timeout", "float", { value: 5 }),
    settingView("access.webhook_api_key", "secret"),
    settingView("jobs.retention_days", "int", { value: 30 }),
  ].map((view) => ({ ...view, ...over[view.key] }));

export const KEY_ADMIN: Record<string, unknown> & { id: string; name: string } = {
  id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  name: "First admin key",
  key_prefix: "lph_adm1",
  scopes: ["admin"],
  allowed_printer_ids: [],
  enabled: true,
  rate_limit_per_minute: 60,
  created_at: "2026-11-01T08:00:00Z",
  expires_at: null,
  last_used_at: "2026-11-04T09:00:00Z",
  last_used_ip: null,
  notes: null,
};
export const KEY_KEPT: typeof KEY_ADMIN = { ...KEY_ADMIN, id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", name: "Kept", key_prefix: "lph_kept", scopes: ["print"], last_used_at: null };

export const ADMIN_PRINTER = {
  id: PRINTER_A.id,
  name: PRINTER_A.name,
  slug: PRINTER_A.slug,
  model: PRINTER_A.model,
  backend: "ptouch",
  connection: { host: "192.0.2.10", port: 9100, snmp: { discover: false, community_set: true } },
  queue: { timeout_s: 30 },
  cut_defaults: { half_cut: false },
  enabled: true,
  created_at: "2026-11-01T08:00:00Z",
  updated_at: "2026-11-01T08:00:00Z",
};

/* Page-printer and sheet fixtures shared by the sheet screens (Plan 4). Typed against the API schema, so a drifting field fails the typecheck. */
type Schemas = components["schemas"];

/** An IPP page printer: the other backend kind next to the tape printers above. */
export const PAGE_PRINTER = {
  ...PRINTER_A,
  id: "33333333-3333-4333-8333-333333333333",
  name: "Office laser",
  slug: "office-laser",
  model: "Example LaserJet",
  backend: "ipp",
  connection: { uri: "ipp://printer.example.invalid/ipp/print", tls_verify: true },
};

export const PAGE_TRAYS: Schemas["TrayStatusRead"][] = [
  { key: "main", label: "Main tray", enabled: true, is_default: true, load_hint: "Print side up", media: "A4" },
  { key: "bypass", label: "Bypass", enabled: true, is_default: false, load_hint: null, media: null },
];

/** `GET /api/v1/printers/{id}/status` of a page printer. */
export const pageStatus = (printerId: string, over: Partial<Schemas["PrinterStatus"]> = {}): Schemas["PrinterStatus"] => ({
  printer_id: printerId,
  online: true,
  kind: "page",
  captured_at: "2026-11-04T10:00:00Z",
  printer_state: "idle",
  state_reasons: [],
  markers: [{ name: "Black toner", color: "#000000", level_percent: 80, low: false, empty: false, some_remaining: true, type: "toner" }],
  trays: PAGE_TRAYS,
  jobs_ahead: 0,
  error_state: null,
  last_error: null,
  last_probe_age_s: 3,
  stale: false,
  polled: true,
  identity_mismatch: false,
  roll_prompt: false,
  note: null,
  tape_loaded: null,
  ...over,
});

export const PAGE_CAPABILITIES: Schemas["Capabilities"] = {
  kind: "page",
  stale: false,
  captured_at: "2026-11-04T10:00:00Z",
  document_formats: ["application/pdf", "image/png"],
  media: {
    hardware_margins_mm: { top: 4, bottom: 4, left: 4, right: 4 },
    media_type_settable: true,
    media_types: ["labels"],
    page_sizes: [{ name: "A4", width_mm: 210, height_mm: 297 }],
  },
  resolution_dpi: { supported: [300, 600], max: 600 },
  trays: [
    { key: "main", label: "Main tray", enabled: true, is_default: true, load_hint: "Print side up", media: "A4", calibration: null },
    { key: "bypass", label: "Bypass", enabled: true, is_default: false, load_hint: null, media: null, calibration: null },
  ],
};

/** A 4 x 12 sheet of 45.7 x 21.2 mm labels on A4 (the shape of the seeded L4736REV type). */
export const GEOMETRY_L4736: Schemas["GeometryMm"] = {
  page_size: "A4",
  page_w: 210,
  page_h: 297,
  cols: 4,
  rows: 12,
  label_w: 45.7,
  label_h: 21.2,
  pitch_x: 48.5,
  pitch_y: 21.2,
  margin_left: 8.4,
  margin_top: 21.5,
  shape: "rectangle",
  corner_radius: 2,
};

export const SHEET_TYPE: Schemas["SheetTypeRead"] = {
  key: "L4736REV",
  prefix: "L4736",
  vendor: "Example Labels",
  description: "48 labels, 45.7 x 21.2 mm",
  geometry: GEOMETRY_L4736,
  current_version: 1,
  origin: "seed",
  verified: true,
  allow_qr: true,
  archived_at: null,
  created_at: "2026-11-01T08:00:00Z",
  updated_at: "2026-11-01T08:00:00Z",
  hints: [],
  notes: null,
  product_codes: ["L4736REV-25"],
  sheets_in_use: 1,
  source_name: null,
  source_url: null,
  source_url_shipped: false,
};

/** A sheet with the given cells in the given state; everything else is free. */
export function sheetRead(
  code = "L4736-0001",
  cells: Partial<Record<Schemas["CellRead"]["state"], number[]>> = { used: [1, 2, 3] },
  over: Partial<Schemas["SheetRead"]> = {},
): Schemas["SheetRead"] {
  const total = GEOMETRY_L4736.cols * GEOMETRY_L4736.rows;
  const rows: Schemas["CellRead"][] = [];
  for (const state of ["used", "reserved", "unconfirmed"] as const) {
    for (const cell of cells[state] ?? []) {
      rows.push({ cell, state, source: "hub", ref: null, purpose: null, marked_by_hand: false, is_id_cell: false, job_id: null, updated_at: "2026-11-04T09:00:00Z" });
    }
  }
  rows.sort((a, b) => a.cell - b.cell);
  const count = (state: Schemas["CellRead"]["state"]) => rows.filter((r) => r.state === state).length;
  return {
    code,
    type_key: SHEET_TYPE.key,
    type_label: "L4736REV",
    version: 1,
    state: "active",
    discarded_at: null,
    total,
    used: count("used"),
    reserved: count("reserved"),
    unconfirmed: count("unconfirmed"),
    free: total - rows.length,
    label_w: GEOMETRY_L4736.label_w,
    label_h: GEOMETRY_L4736.label_h,
    geometry: GEOMETRY_L4736,
    id_placement: "cell",
    id_printed: true,
    feed_mark_printed: false,
    last_used_at: "2026-11-04T09:00:00Z",
    note: null,
    cells: rows,
    ...over,
  };
}

export function sheetSummary(code = "L4736-0001", over: Partial<Schemas["SheetSummary"]> = {}): Schemas["SheetSummary"] {
  const sheet = sheetRead(code);
  return {
    code: sheet.code,
    type_key: sheet.type_key,
    type_label: sheet.type_label,
    version: sheet.version,
    state: sheet.state,
    total: sheet.total,
    used: sheet.used,
    reserved: sheet.reserved,
    unconfirmed: sheet.unconfirmed,
    free: sheet.free,
    label_w: sheet.label_w,
    label_h: sheet.label_h,
    last_used_at: sheet.last_used_at,
    ...over,
  };
}

/** `POST /api/v1/print/{printer}/sheet/preview`: one page with three new labels. */
export const sheetPreview = (over: Partial<Schemas["SheetPreview"]> = {}): Schemas["SheetPreview"] => ({
  pages: [
    {
      type_key: SHEET_TYPE.key,
      version: 1,
      sheet_code: "L4736-0001",
      new_code_hint: null,
      geometry: GEOMETRY_L4736,
      cells: [4, 5, 6].map((cell, i) => ({
        cell,
        state: "new" as const,
        item_index: i,
        purpose: null,
        is_id: false,
        hw_margin: false,
        mapped: true,
        truncated: false,
      })),
      png_base64: "iVBORw0KGgo=",
      margin_band: null,
      margin_id: false,
      id_not_printed: false,
      feed_mark: false,
      load_hint: "Print side up",
    },
  ],
  free_after: [7, 8, 9],
  reprint_hints: [],
  expected_cells: [{ sheet: "L4736-0001", cells: [4, 5, 6], id_cell: null }],
  placed: 3,
  remaining: 0,
  ...over,
});

export const PRINTED_PAGE: Schemas["PrintedPage"] = {
  job_id: "44444444-4444-4444-8444-444444444444",
  sheet_code: "L4736-0001",
  cells: [4, 5, 6],
  id_cell: null,
  id_not_printed: false,
  margin_band: null,
  margin_id: false,
  feed_mark: false,
};

/** The envelope the API answers errors with; `detail` carries the structured data of the code. */
export const apiErrorBody = (code: string, message: string, detail?: Record<string, unknown>) => ({
  detail: { error_code: code, error_message: message, ...(detail ? { error_detail: detail } : {}) },
});
