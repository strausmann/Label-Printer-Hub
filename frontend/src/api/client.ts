/**
 * Thin fetch wrapper for the backend API (D1: same origin, so the session cookie is enough).
 * Types come from `schema.gen.ts`, generated from the backend's OpenAPI (`pnpm gen:api`).
 */

export const CSRF_HEADER = "X-CSRF-Token";

const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

/** An error response from the API, or `status` 0 when the server could not be reached. */
export class ApiError extends Error {
  readonly status: number;
  /** Machine-readable code (`error_code`, or the problem `type`); null when the body has none. */
  readonly code: string | null;
  readonly detail: string;
  /**
   * The structured data an error carries (`detail.error_detail` of the envelope, `extensions` of
   * a problem): the free cells of `insufficient_cells`, the plan of `plan_changed`. Null when none.
   */
  readonly errorDetail: Record<string, unknown> | null;

  constructor(status: number, code: string | null, detail: string, errorDetail: Record<string, unknown> | null = null) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.detail = detail;
    this.errorDetail = errorDetail;
  }
}

let csrfToken: string | null = null;
/**
 * What the server said when asked whether the session is still there: `valid`, `signed_out`
 * (definitive), or `unknown` (no definitive answer: network error, 5xx).
 */
export type SessionVerdict = "valid" | "signed_out" | "unknown";

type UnauthorizedHandler = () => void | Promise<SessionVerdict>;

let onUnauthorized: UnauthorizedHandler | null = null;
let sessionUnknown = false;
const unknownListeners = new Set<() => void>();
const confirmedListeners = new Set<() => void>();

/** While the session is unverified, requests that change state are refused (see `apiFetch`). */
export function setSessionUnknown(value: boolean): void {
  if (value === sessionUnknown) return;
  sessionUnknown = value;
  unknownListeners.forEach((l) => l());
}

export function isSessionUnknown(): boolean {
  return sessionUnknown;
}

export function subscribeSessionUnknown(listener: () => void): () => void {
  unknownListeners.add(listener);
  return () => void unknownListeners.delete(listener);
}

/** Called once a revalidation after an `unknown` answer found the session valid again. */
export function onSessionConfirmed(listener: () => void): () => void {
  confirmedListeners.add(listener);
  return () => void confirmedListeners.delete(listener);
}

export function emitSessionConfirmed(): void {
  [...confirmedListeners].forEach((l) => l());
}

/** The session state (Task 9) registers the CSRF token it got from `GET /api/v1/auth/session`. */
export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

/** Registers the handler for 401 responses (the shell sends the user to sign-in). */
export function setOnUnauthorized(handler: UnauthorizedHandler | null): void {
  onUnauthorized = handler;
}

/**
 * Runs the registered 401 handler; the event stream calls it when the server ends the stream.
 * The handler asks the server whether the session is really gone (an SSO session renews itself,
 * a key's printers changed): `valid`, `signed_out`, or `unknown` when no answer came.
 */
export async function notifyUnauthorized(): Promise<SessionVerdict> {
  if (!onUnauthorized) return "signed_out";
  return (await onUnauthorized()) ?? "signed_out";
}

/** `as: "blob"` returns the body as a Blob (images); the default parses JSON. */
export type ApiInit = RequestInit & {
  json?: unknown;
  as?: "json" | "blob";
  /** A 401 is returned as an error without running the unauthorized handler (it asks this very question). */
  skipUnauthorized?: boolean;
};

type Json = Record<string, unknown>;

function isObject(value: unknown): value is Json {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * The backend answers errors in two shapes: RFC 7807 problems (`type`, `title`, `detail`)
 * and FastAPI exceptions (`detail: { error_code, error_message }` or `detail: "text"`).
 */
function parseProblem(status: number, body: unknown): ApiError {
  const fallback = `HTTP ${status}`;
  if (!isObject(body)) return new ApiError(status, null, fallback);
  const d = body.detail;
  if (isObject(d)) {
    // A problem object raised as a FastAPI exception arrives wrapped: `detail: { type, title, detail }`.
    const wrapped = typeof d.type === "string" && d.type !== "about:blank" ? d.type : null;
    const code = typeof d.error_code === "string" ? d.error_code : wrapped;
    const message =
      typeof d.error_message === "string"
        ? d.error_message
        : typeof d.detail === "string"
          ? d.detail
          : typeof d.title === "string"
            ? d.title
            : fallback;
    return new ApiError(status, code, message, isObject(d.error_detail) ? d.error_detail : null);
  }
  const code = typeof body.type === "string" && body.type !== "about:blank" ? body.type : null;
  const extensions = isObject(body.extensions) ? body.extensions : null;
  if (typeof d === "string") return new ApiError(status, code, d, extensions);
  const title = typeof body.title === "string" ? body.title : fallback;
  return new ApiError(status, code, title, extensions);
}

async function readBody(response: Response): Promise<unknown> {
  const type = response.headers.get("Content-Type") ?? "";
  if (!/json/i.test(type)) return undefined;
  try {
    return await response.json();
  } catch {
    return undefined;
  }
}

export async function apiFetch<T>(path: string, init: ApiInit = {}): Promise<T> {
  const { json, as: bodyAs = "json", skipUnauthorized = false, headers: initHeaders, ...rest } = init;
  const method = (rest.method ?? "GET").toUpperCase();
  const headers = new Headers(initHeaders);
  if (json !== undefined) headers.set("Content-Type", "application/json");
  if (!headers.has("Accept")) headers.set("Accept", "application/json");
  if (UNSAFE_METHODS.has(method) && csrfToken) headers.set(CSRF_HEADER, csrfToken);

  // No definitive answer about the session yet: do not send writes on a session that may be gone
  // or may belong to someone else by now. Reads and the session endpoint itself still go out.
  if (sessionUnknown && UNSAFE_METHODS.has(method) && !path.startsWith("/api/v1/auth/session")) {
    throw new ApiError(0, "session_unknown", "Checking your session. Try again in a moment.");
  }

  let response: Response;
  try {
    response = await fetch(path, {
      ...rest,
      method,
      headers,
      credentials: "same-origin",
      body: json !== undefined ? JSON.stringify(json) : rest.body,
    });
  } catch {
    throw new ApiError(0, "network_error", "Network error");
  }

  if (!response.ok) {
    const error = parseProblem(response.status, await readBody(response));
    if (response.status === 401 && !skipUnauthorized) void onUnauthorized?.();
    throw error;
  }
  if (response.status === 204) return undefined as T;
  if (bodyAs === "blob") return (await response.blob()) as T;
  return (await readBody(response)) as T;
}
