import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, apiFetch, setCsrfToken, setOnUnauthorized } from "./client";

function respond(status: number, body?: unknown, contentType = "application/json"): Response {
  return new Response(body === undefined ? null : typeof body === "string" ? body : JSON.stringify(body), {
    status,
    headers: body === undefined ? {} : { "Content-Type": contentType },
  });
}

describe("apiFetch", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
    setCsrfToken("test-csrf-token");
    setOnUnauthorized(null);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    setCsrfToken(null);
    setOnUnauthorized(null);
  });

  function lastInit(): RequestInit {
    return fetchMock.mock.calls.at(-1)![1] as RequestInit;
  }
  function lastHeaders(): Headers {
    return new Headers(lastInit().headers);
  }

  it("sends same-origin credentials and parses JSON", async () => {
    fetchMock.mockResolvedValue(respond(200, { ok: true }));
    await expect(apiFetch<{ ok: boolean }>("/api/info")).resolves.toEqual({ ok: true });
    expect(fetchMock.mock.calls[0]![0]).toBe("/api/info");
    expect(lastInit().credentials).toBe("same-origin");
  });

  it("sends csrf header on POST, not on GET", async () => {
    fetchMock.mockResolvedValue(respond(200, {}));
    await apiFetch("/api/v1/things");
    expect(lastHeaders().has("X-CSRF-Token")).toBe(false);

    await apiFetch("/api/v1/things", { method: "POST", json: { a: 1 } });
    expect(lastHeaders().get("X-CSRF-Token")).toBe("test-csrf-token");
    expect(lastHeaders().get("Content-Type")).toBe("application/json");
    expect(lastInit().body).toBe('{"a":1}');

    for (const method of ["PUT", "PATCH", "DELETE"]) {
      await apiFetch("/api/v1/things/1", { method });
      expect(lastHeaders().get("X-CSRF-Token"), method).toBe("test-csrf-token");
    }
  });

  it("omits the csrf header when no session token is known", async () => {
    setCsrfToken(null);
    fetchMock.mockResolvedValue(respond(200, {}));
    await apiFetch("/api/v1/things", { method: "POST" });
    expect(lastHeaders().has("X-CSRF-Token")).toBe(false);
  });

  it("returns undefined for 204", async () => {
    fetchMock.mockResolvedValue(respond(204));
    await expect(apiFetch("/api/v1/things/1", { method: "DELETE" })).resolves.toBeUndefined();
  });

  it("parses problem body into ApiError", async () => {
    fetchMock.mockResolvedValue(
      respond(409, { type: "tape-mismatch", title: "Tape Mismatch", status: 409, detail: "Loaded 12 mm, expected 24 mm" }, "application/problem+json"),
    );
    const err = await apiFetch("/api/v1/jobs").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 409, code: "tape-mismatch", detail: "Loaded 12 mm, expected 24 mm" });
  });

  it("parses the error_code / error_message detail shape", async () => {
    fetchMock.mockResolvedValue(respond(403, { detail: { error_code: "csrf_failed", error_message: "Missing header." } }));
    await expect(apiFetch("/api/v1/x", { method: "POST" })).rejects.toMatchObject({
      status: 403,
      code: "csrf_failed",
      detail: "Missing header.",
    });
  });

  it("falls back to a string detail, then to the status text", async () => {
    fetchMock.mockResolvedValueOnce(respond(404, { detail: "Not Found" }));
    await expect(apiFetch("/api/v1/x")).rejects.toMatchObject({ status: 404, code: null, detail: "Not Found" });

    fetchMock.mockResolvedValueOnce(respond(502, "<html>bad gateway</html>", "text/html"));
    await expect(apiFetch("/api/v1/x")).rejects.toMatchObject({ status: 502, code: null, detail: "HTTP 502" });
  });

  it("calls onUnauthorized on 401", async () => {
    const onUnauthorized = vi.fn();
    setOnUnauthorized(onUnauthorized);
    fetchMock.mockResolvedValue(respond(401, { detail: { error_code: "not_signed_in", error_message: "Sign in." } }));
    await expect(apiFetch("/api/v1/printers")).rejects.toMatchObject({ status: 401, code: "not_signed_in" });
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
  });

  it("does not call onUnauthorized for other errors", async () => {
    const onUnauthorized = vi.fn();
    setOnUnauthorized(onUnauthorized);
    fetchMock.mockResolvedValue(respond(403, { detail: "no" }));
    await expect(apiFetch("/api/v1/printers")).rejects.toBeInstanceOf(ApiError);
    expect(onUnauthorized).not.toHaveBeenCalled();
  });

  it("network failure rejects with ApiError status 0", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    const err = await apiFetch("/api/info").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 0, code: "network_error" });
  });

  describe("errorDetail", () => {
    it("keeps detail.error_detail from the envelope shape", async () => {
      fetchMock.mockResolvedValue(
        respond(409, { detail: { error_code: "insufficient_cells", error_message: "Short.", error_detail: { needed: 5, shortfall: 2 } } }),
      );
      const err = await apiFetch("/api/sheets").catch((e: unknown) => e);
      expect(err).toMatchObject({ status: 409, code: "insufficient_cells", errorDetail: { needed: 5, shortfall: 2 } });
    });

    it("keeps extensions from the problem shape", async () => {
      fetchMock.mockResolvedValue(
        respond(503, { type: "printer-unavailable", title: "Printer unavailable", extensions: { printer: "p1" } }),
      );
      const err = await apiFetch("/api/x").catch((e: unknown) => e);
      expect(err).toMatchObject({ code: "printer-unavailable", errorDetail: { printer: "p1" } });
    });

    it("is null when the body carries no detail object", async () => {
      fetchMock.mockResolvedValueOnce(respond(404, { detail: "Not Found" }));
      expect(await apiFetch("/x").catch((e: unknown) => e)).toMatchObject({ errorDetail: null });
      fetchMock.mockResolvedValueOnce(respond(409, { detail: { error_code: "a", error_message: "b", error_detail: null } }));
      expect(await apiFetch("/x").catch((e: unknown) => e)).toMatchObject({ errorDetail: null });
      fetchMock.mockResolvedValueOnce(respond(409, { detail: { error_code: "a", error_message: "b", error_detail: ["no"] } }));
      expect(await apiFetch("/x").catch((e: unknown) => e)).toMatchObject({ errorDetail: null });
    });

    it("network and session errors have a null errorDetail", async () => {
      fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
      expect(await apiFetch("/x").catch((e: unknown) => e)).toMatchObject({ errorDetail: null });
    });
  });
});
