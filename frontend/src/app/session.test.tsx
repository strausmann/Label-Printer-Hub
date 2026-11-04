import { act, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { apiFetch, setCsrfToken, setOnUnauthorized } from "../api/client";
import { installUnauthorizedGuard, SESSION_KEY } from "./session";
import { renderApp, SIGNED_IN, SIGNED_OUT } from "../test-utils";

afterEach(() => {
  setOnUnauthorized(null);
  setCsrfToken(null);
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
    ["/sign-in", undefined],
    ["/sign-in?redirect=/jobs", undefined],
    [42, undefined],
  ])("%s -> %s", async (input, expected) => {
    const { safeRedirect } = await import("./router");
    expect(safeRedirect(input)).toBe(expected);
  });
});
