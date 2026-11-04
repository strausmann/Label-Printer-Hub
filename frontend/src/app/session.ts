import { useMutation, useQuery, useQueryClient, type QueryClient, type UseQueryResult } from "@tanstack/react-query";
import { useCallback, useEffect } from "react";
import { apiFetch, setCsrfToken, setOnUnauthorized } from "../api/client";
import type { components } from "../api/schema.gen";

export type InfoData = components["schemas"]["Info"];
export type SessionData = components["schemas"]["SessionInfo"];

export const INFO_KEY = ["info"] as const;
export const SESSION_KEY = ["session"] as const;

export const SIGNED_OUT: SessionData = { signed_in: false, bootstrap: false };

/** Public build/auth/feature info; needed before anyone is signed in. */
export function useInfo(): UseQueryResult<InfoData> {
  return useQuery({
    queryKey: INFO_KEY,
    queryFn: () => apiFetch<InfoData>("/api/info"),
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

export function useSession(): Session {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: SESSION_KEY,
    queryFn: () => apiFetch<SessionData>("/api/v1/auth/session"),
    staleTime: 30_000,
  });
  const data = query.data;
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
    onSettled: () => {
      setCsrfToken(null);
      resetUserData(queryClient);
      queryClient.setQueryData(SESSION_KEY, SIGNED_OUT);
    },
  });

  const signIn = useCallback((key: string) => signInMutation.mutateAsync(key).then(() => undefined), [signInMutation]);
  const signOut = useCallback(() => signOutMutation.mutateAsync().catch(() => undefined), [signOutMutation]);

  return {
    isPending: query.isPending,
    isError: query.isError && !data,
    signedIn: data?.signed_in ?? false,
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

/**
 * Any 401 means the session is gone: mark it signed out. The router then shows the
 * sign-in screen and remembers where the user was (the root layout does the redirect).
 */
export function installUnauthorizedGuard(queryClient: QueryClient): () => void {
  setOnUnauthorized(() => {
    setCsrfToken(null);
    queryClient.setQueryData(SESSION_KEY, SIGNED_OUT);
  });
  return () => setOnUnauthorized(null);
}
