import { act, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { apiFetch, isSessionUnknown, setCsrfToken, setOnUnauthorized, setSessionUnknown } from "../api/client";
import { installUnauthorizedGuard, SESSION_KEY } from "./session";
import { renderApp, SIGNED_IN, SIGNED_OUT } from "../test-utils";

afterEach(() => {
  setOnUnauthorized(null);
  setCsrfToken(null);
  setSessionUnknown(false);
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

function stubFetch(handler: (url: string, init?: RequestInit) => Response | Promise<Response>) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => handler(String(input), init));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

describe("session", () => {
  it("401 from any query routes to /sign-in", async () => {
    const { queryClient, router } = await renderApp({ path: "/jobs" });
    installUnauthorizedGuard(queryClient);
    expect(router.state.location.pathname).toBe("/jobs");
    stubFetch(() => json({ detail: "expired" }, 401));
    await act(async () => {
      await apiFetch("/api/v1/jobs").catch(() => undefined);
    });
    await waitFor(() => expect(router.state.location.pathname).toBe("/sign-in"));
    // The page the user was on is remembered, and the sign-in screen is shown.
    expect(router.state.location.search).toMatchObject({ redirect: "/jobs" });
    expect(await screen.findByRole("button", { name: "Sign in" })).toBeInTheDocument();
    expect(queryClient.getQueryData(SESSION_KEY)).toMatchObject({ signed_in: false });
  });

  describe("a 401 asks the server before it ends the session", () => {
    const fresh = { ...SIGNED_IN, csrf_token: "fresh-csrf-token" };

    it("keeps an SSO user signed in when the session endpoint answers with a new session", async () => {
      localStorage.setItem("lph.recent.snipeit", JSON.stringify([{ id: "1", name: "A", kind: "asset", at: 1 }]));
      const { queryClient, router } = await renderApp({ path: "/jobs" });
      installUnauthorizedGuard(queryClient);
      const fetchMock = stubFetch((url) =>
        url === "/api/v1/auth/session" ? json(fresh) : json({ detail: "expired" }, 401),
      );
      await act(async () => {
        await apiFetch("/api/v1/jobs").catch(() => undefined);
      });
      await waitFor(() => expect(queryClient.getQueryData(SESSION_KEY)).toMatchObject({ csrf_token: "fresh-csrf-token" }));
      expect(router.state.location.pathname).toBe("/jobs");
      expect(localStorage.getItem("lph.recent.snipeit")).not.toBeNull();
      expect(fetchMock.mock.calls.filter(([u]) => String(u) === "/api/v1/auth/session")).toHaveLength(1);
    });

    it("signs out, forgets recent items and user data when the server says signed_out", async () => {
      localStorage.setItem("lph.recent.snipeit", JSON.stringify([{ id: "1", name: "A", kind: "asset", at: 1 }]));
      const { queryClient, router } = await renderApp({ path: "/jobs" });
      installUnauthorizedGuard(queryClient);
      queryClient.setQueryData(["printers"], [{ id: "p1" }]);
      stubFetch((url) => (url === "/api/v1/auth/session" ? json(SIGNED_OUT) : json({ detail: "expired" }, 401)));
      await act(async () => {
        await apiFetch("/api/v1/jobs").catch(() => undefined);
      });
      await waitFor(() => expect(router.state.location.pathname).toBe("/sign-in"));
      expect(queryClient.getQueryData(SESSION_KEY)).toMatchObject({ signed_in: false });
      expect(queryClient.getQueryData(["printers"])).toBeUndefined();
      expect(localStorage.getItem("lph.recent.snipeit")).toBeNull();
    });

    it("drops the previous user's cached data when the session comes back as someone else", async () => {
      localStorage.setItem("lph.recent.snipeit", JSON.stringify([{ id: "1", name: "A", kind: "asset", at: 1 }]));
      const { queryClient } = await renderApp({ path: "/jobs", session: { ...SIGNED_IN, user: "user-a" } });
      installUnauthorizedGuard(queryClient);
      queryClient.setQueryData(["jobs"], [{ id: "a-job" }]);
      queryClient.setQueryData(["printers"], [{ id: "a-printer" }]);
      stubFetch((url) =>
        url === "/api/v1/auth/session" ? json({ ...SIGNED_IN, user: "user-b" }) : json({ detail: "expired" }, 401),
      );
      await act(async () => {
        await apiFetch("/api/v1/jobs").catch(() => undefined);
      });
      await waitFor(() => expect(queryClient.getQueryData(SESSION_KEY)).toMatchObject({ user: "user-b" }));
      expect(queryClient.getQueryData(["jobs"])).toBeUndefined();
      expect(queryClient.getQueryData(["printers"])).toBeUndefined();
      expect(localStorage.getItem("lph.recent.snipeit")).toBeNull();
    });

    it("keeps the screen but refuses writes when the server gives no definitive answer, and retries", async () => {
      const { queryClient, router } = await renderApp({ path: "/jobs" });
      installUnauthorizedGuard(queryClient);
      vi.useFakeTimers();
      let healthy = false;
      const fetchMock = stubFetch((url) => {
        if (url === "/api/v1/auth/session") return healthy ? json(SIGNED_IN) : json({ detail: "down" }, 503);
        return json({ detail: "expired" }, 401);
      });
      await act(async () => {
        await apiFetch("/api/v1/jobs").catch(() => undefined);
      });
      expect(router.state.location.pathname).toBe("/jobs");
      expect(queryClient.getQueryData(SESSION_KEY)).toMatchObject({ signed_in: true });
      expect(isSessionUnknown()).toBe(true);
      // Reads still go out; a write does not leave the browser.
      const before = fetchMock.mock.calls.length;
      await expect(apiFetch("/api/v1/jobs/1/retry", { method: "POST" })).rejects.toMatchObject({ code: "session_unknown" });
      expect(fetchMock.mock.calls.length).toBe(before);
      // The check repeats with backoff; a definitive answer lifts the hold.
      await act(async () => void (await vi.advanceTimersByTimeAsync(2000)));
      expect(isSessionUnknown()).toBe(true);
      healthy = true;
      await act(async () => void (await vi.advanceTimersByTimeAsync(4000)));
      expect(isSessionUnknown()).toBe(false);
      expect(router.state.location.pathname).toBe("/jobs");
    });

    it("signs out when a later retry gets a definitive signed_out", async () => {
      const { queryClient, router } = await renderApp({ path: "/jobs" });
      installUnauthorizedGuard(queryClient);
      vi.useFakeTimers();
      let down = true;
      stubFetch((url) => {
        if (url === "/api/v1/auth/session") return down ? json({ detail: "down" }, 503) : json(SIGNED_OUT);
        return json({ detail: "expired" }, 401);
      });
      await act(async () => {
        await apiFetch("/api/v1/jobs").catch(() => undefined);
      });
      down = false;
      await act(async () => void (await vi.advanceTimersByTimeAsync(2000)));
      vi.useRealTimers();
      await waitFor(() => expect(router.state.location.pathname).toBe("/sign-in"));
      expect(isSessionUnknown()).toBe(false);
    });
  });

  it("sends a signed-out visitor of a client route to sign-in and back after signing in", async () => {
    const { router, queryClient } = await renderApp({ path: "/jobs/7f9c1c2e", session: SIGNED_OUT });
    await waitFor(() => expect(router.state.location.pathname).toBe("/sign-in"));
    expect(router.state.location.search).toMatchObject({ redirect: "/jobs/7f9c1c2e" });
    act(() => {
      queryClient.setQueryData(SESSION_KEY, SIGNED_IN);
    });
    await waitFor(() => expect(router.state.location.pathname).toBe("/jobs/7f9c1c2e"));
  });

  it("never follows an off-site redirect target", async () => {
    const { router } = await renderApp({ path: "/sign-in?redirect=//evil.example.invalid/x", session: SIGNED_IN });
    await waitFor(() => expect(router.state.location.pathname).toBe("/"));
  });

  it("keeps the CSRF token of the session for state-changing requests", async () => {
    await renderApp({ path: "/" });
    const fetchMock = stubFetch(() => json({}, 200));
    await apiFetch("/api/x", { method: "POST", json: {} });
    const headers = new Headers(fetchMock.mock.calls[0]?.[1]?.headers);
    expect(headers.get("X-CSRF-Token")).toBe("csrf-test");
  });
});

describe("safeRedirect", () => {
  it.each([
    ["/jobs/1?x=1#y", "/jobs/1?x=1#y"],
    ["//evil.example.invalid", undefined],
    ["/\\evil.example.invalid", undefined],
    ["https://evil.example.invalid/x", undefined],
    ["jobs", undefined],
    ["/\t/evil.example.invalid", undefined],
    ["/jobs\n/1", undefined],
    ["/jobs\u0000", undefined],
    ["/sign-in", undefined],
    ["/sign-in?redirect=/jobs", undefined],
    [42, undefined],
  ])("%s -> %s", async (input, expected) => {
    const { safeRedirect } = await import("./router");
    expect(safeRedirect(input)).toBe(expected);
  });
});
