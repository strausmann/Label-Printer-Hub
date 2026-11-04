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
export interface Call {
  method: string;
  path: string;
  headers: Headers;
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
    calls.push({ method, path: url.pathname, headers: new Headers(init.headers) });
    const route = routes[`${method} ${url.pathname}`];
    if (route === undefined) {
      return new Response(JSON.stringify({ detail: "not mocked" }), { status: 404, headers: { "Content-Type": "application/json" } });
    }
    const body = typeof route === "function" ? (route as Handler)(init) : route;
    if (body === null) return new Response(null, { status: 204 });
    return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
  });
  vi.stubGlobal("fetch", fetchMock);
  return { calls, fetchMock };
}
