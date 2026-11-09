import { useMutation, useQuery, useQueryClient, type QueryClient, type UseQueryResult } from "@tanstack/react-query";
import { useCallback, useEffect, useSyncExternalStore } from "react";
import {
  ApiError,
  apiFetch,
  emitSessionConfirmed,
  isSessionUnknown,
  setCsrfToken,
  setOnUnauthorized,
  setSessionUnknown,
  subscribeSessionUnknown,
  type SessionVerdict,
} from "../api/client";
import type { components } from "../api/schema.gen";
import { clearRecent } from "../features/lookup/recent";

export type InfoData = components["schemas"]["Info"];
export type SessionData = components["schemas"]["SessionInfo"];

export const INFO_KEY = ["info"] as const;
export const SESSION_KEY = ["session"] as const;

export const SIGNED_OUT: SessionData = { signed_in: false, bootstrap: false };

/** Public build/auth/feature info; needed before anyone is signed in. */
export function useInfo(): UseQueryResult<InfoData> {
  return useQuery({
    queryKey: INFO_KEY,
    queryFn: () => apiFetch<InfoData>("/api/v1/info"),
    staleTime: 60_000,
  });
}

/** Whether a module is available (spec 5.3). Unknown or still loading counts as off. */
export function useFeature(name: string): boolean {
  return useInfo().data?.features[name] ?? false;
}

export interface Session {
  /** True until the first answer of the server is in. */
  isPending: boolean;
  /** The session state could not be read at all (server down), as opposed to "signed out". */
  isError: boolean;
  signedIn: boolean;
  /** The server could not confirm the session after a 401 (no definitive answer yet); writes wait. */
  unverified: boolean;
  scope: SessionData["scope"];
  source: SessionData["source"];
  user: string | null;
  /** A bootstrap session: it may only create the first admin key (D7). */
  bootstrap: boolean;
  csrfToken: string | null;
  refetch: () => Promise<unknown>;
  signIn: (key: string) => Promise<void>;
  signOut: () => Promise<void>;
}

/** Drop everything the previous user could see; keep what is public. */
function resetUserData(queryClient: QueryClient): void {
  queryClient.removeQueries({ predicate: (q) => q.queryKey[0] !== INFO_KEY[0] && q.queryKey[0] !== SESSION_KEY[0] });
}

/** The session ended: drop everything the previous user could see (data, recent lookups, CSRF). */
function endSession(queryClient: QueryClient): void {
  setCsrfToken(null);
  resetUserData(queryClient);
  clearRecent();
  queryClient.setQueryData(SESSION_KEY, SIGNED_OUT);
}

/** Another person (or another role) behind the same cookie must not inherit the cached data. */
function sameIdentity(a: SessionData | undefined, b: SessionData): boolean {
  return !!a && a.signed_in && a.user === b.user && a.source === b.source && a.scope === b.scope && a.bootstrap === b.bootstrap;
}

/**
 * Every session answer from the server goes through here before it is stored: a signed-out
 * answer, or a different identity than the one the cache was filled for, drops the previous
 * user's data and recent lookups first (focus refetch, 401 revalidation and the stream alike).
 */
function checkIdentity(queryClient: QueryClient, next: SessionData): void {
  const previous = queryClient.getQueryData<SessionData>(SESSION_KEY);
  if (!next.signed_in) {
    setCsrfToken(null);
    resetUserData(queryClient);
    clearRecent();
  } else if (previous?.signed_in && !sameIdentity(previous, next)) {
    resetUserData(queryClient);
    clearRecent();
  }
}

export function useSession(): Session {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: SESSION_KEY,
    queryFn: async () => {
      const next = await apiFetch<SessionData>("/api/v1/auth/session");
      checkIdentity(queryClient, next);
      return next;
    },
    staleTime: 30_000,
  });
  const data = query.data;
  const unverified = useSyncExternalStore(subscribeSessionUnknown, isSessionUnknown);
  const csrfToken = data?.signed_in ? (data.csrf_token ?? null) : null;

  useEffect(() => {
    setCsrfToken(csrfToken);
  }, [csrfToken]);

  const signInMutation = useMutation({
    mutationFn: async (key: string) => {
      await apiFetch<void>("/api/v1/auth/session", { method: "POST", json: { key } });
      return apiFetch<SessionData>("/api/v1/auth/session");
    },
    onSuccess: (next) => {
      resetUserData(queryClient);
      queryClient.setQueryData(SESSION_KEY, next);
    },
  });

  const signOutMutation = useMutation({
    mutationFn: () => apiFetch<void>("/api/v1/auth/session", { method: "DELETE" }),
    // A failed sign-out (already expired, server gone) still ends the session here.
    onSettled: () => endSession(queryClient),
  });

  const signIn = useCallback((key: string) => signInMutation.mutateAsync(key).then(() => undefined), [signInMutation]);
  const signOut = useCallback(() => signOutMutation.mutateAsync().catch(() => undefined), [signOutMutation]);

  return {
    isPending: query.isPending,
    isError: query.isError && !data,
    signedIn: data?.signed_in ?? false,
    unverified,
    scope: data?.scope ?? null,
    source: data?.source ?? null,
    user: data?.user ?? null,
    bootstrap: data?.bootstrap ?? false,
    csrfToken,
    refetch: query.refetch,
    signIn,
    signOut,
  };
}

const RETRY_START_MS = 2_000;
const RETRY_MAX_MS = 30_000;

let pendingCheck: Promise<SessionVerdict> | null = null;
let retryTimer: ReturnType<typeof setTimeout> | null = null;
let retryDelay = RETRY_START_MS;
// A server that keeps answering 401 to data requests while the session endpoint says "valid"
// would make refetch -> 401 -> revalidate -> refetch loop forever; refetch at most once per window.
const REFETCH_COOLDOWN_MS = 10_000;
let lastRefetchAt = 0;

function stopRetrying(): void {
  if (retryTimer) clearTimeout(retryTimer);
  retryTimer = null;
  retryDelay = RETRY_START_MS;
}

function settle(queryClient: QueryClient, verdict: SessionVerdict, next?: SessionData): void {
  if (verdict === "unknown") {
    // Keep what is on screen, but nothing is sent that changes state until the server answers.
    setSessionUnknown(true);
    if (!retryTimer) {
      retryTimer = setTimeout(() => {
        retryTimer = null;
        void revalidateSession(queryClient);
      }, retryDelay);
      retryDelay = Math.min(retryDelay * 2, RETRY_MAX_MS);
    }
    return;
  }
  const wasUnknown = isSessionUnknown();
  stopRetrying();
  setSessionUnknown(false);
  if (verdict === "signed_out" || !next) {
    endSession(queryClient);
    return;
  }
  checkIdentity(queryClient, next);
  queryClient.setQueryData(SESSION_KEY, next);
  if (Date.now() - lastRefetchAt >= REFETCH_COOLDOWN_MS) {
    lastRefetchAt = Date.now();
    void queryClient.invalidateQueries({ predicate: (q) => q.queryKey[0] !== INFO_KEY[0] && q.queryKey[0] !== SESSION_KEY[0] });
  }
  if (wasUnknown) emitSessionConfirmed();
}

/**
 * Asks the server whether the session is really gone. A 401 or an `auth.expired` frame is not
 * proof: a trusted SSO session is renewed by this very request, and a key whose printer
 * restriction changed keeps its session. Only a `signed_in: false` answer (or a 401 on the
 * session endpoint itself) ends it. When the server cannot be asked (network error, 5xx) the
 * answer is `unknown`: the screen stays, writes wait, and the question is repeated with backoff.
 * A session that comes back as another identity drops the previous user's cached data.
 */
function revalidateSession(queryClient: QueryClient): Promise<SessionVerdict> {
  pendingCheck ??= (async (): Promise<SessionVerdict> => {
    let verdict: SessionVerdict;
    let next: SessionData | undefined;
    try {
      next = await apiFetch<SessionData>("/api/v1/auth/session", { skipUnauthorized: true });
      verdict = next.signed_in ? "valid" : "signed_out";
    } catch (error) {
      verdict = error instanceof ApiError && error.status === 401 ? "signed_out" : "unknown";
    }
    settle(queryClient, verdict, next);
    return verdict;
  })().finally(() => {
    pendingCheck = null;
  });
  return pendingCheck;
}

/**
 * Any 401 may mean the session is gone: the server is asked, and only a "signed out" answer
 * marks it so. The router then shows the sign-in screen and remembers where the user was
 * (the root layout does the redirect).
 */
export function installUnauthorizedGuard(queryClient: QueryClient): () => void {
  setOnUnauthorized(() => revalidateSession(queryClient));
  return () => {
    setOnUnauthorized(null);
    lastRefetchAt = 0;
    stopRetrying();
    setSessionUnknown(false);
  };
}
