import { vi } from "vitest";

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
  note: null,
  tape_loaded: "12mm laminated blue/white",
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

type Handler = (init: RequestInit) => unknown;

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
    const body = typeof route === "function" ? (route as Handler)(init) : route;
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
    settingView("general.display_name", "str", { value: "Label Printer Hub", is_set: true }),
    settingView("general.language", "enum", { value: "en", choices: ["en", "de"] }),
    settingView("general.time_zone", "str", { value: "UTC" }),
    settingView("general.public_url", "url", { value: "https://hub.example.invalid", is_set: true, locked: true }),
    settingView("integrations.snipeit.url", "url", { value: "https://assets.example.invalid", is_set: true }),
    settingView("integrations.snipeit.api_key", "secret", { is_set: true }),
    settingView("integrations.snipeit.timeout", "float", { value: 5 }),
    settingView("integrations.grocy.url", "url", { value: "" }),
    settingView("integrations.grocy.api_key", "secret"),
    settingView("integrations.grocy.timeout", "float", { value: 5 }),
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
  connection: { host: "192.0.2.10", port: 9100, snmp: { discover: false, community: "public" } },
  queue: { timeout_s: 30 },
  cut_defaults: { half_cut: false },
  enabled: true,
  created_at: "2026-11-01T08:00:00Z",
  updated_at: "2026-11-01T08:00:00Z",
};
