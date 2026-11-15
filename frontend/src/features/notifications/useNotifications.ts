// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useQueries, useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useSyncExternalStore } from "react";
import { apiFetch } from "../../api/client";
import { queryString } from "../../api/queryString";
import { useFeature } from "../../app/session";
import { printerStatusQuery, usePrinters, type Job, type PrinterStatus } from "../printers/api";
import { useSheets } from "../sheets/api";
import { deriveNotices, deriveNotifications, newestFirst, NOTICES_KEY, WINDOW_MS, type Notification, type SheetTypeNotice } from "./derive";
import { badgeOf, clearAll, dismiss, isVisible, markAllRead, notificationStore, trackFirstSeen, type StoredState } from "./store";

/** Under `["jobs"]`, the prefix every job event invalidates (and the reconnect resync re-reads). */
export const notificationJobsKey = ["jobs", "notifications"] as const;
const JOB_LIMIT = 200;

export type FeedStatus = "loading" | "error" | "ready";

export interface Feed {
  /** Every derived entry, newest first. */
  entries: Notification[];
  /** The entries that are neither cleared nor dismissed: what the panel lists. */
  visible: Notification[];
  state: StoredState;
  badge: ReturnType<typeof badgeOf>;
  status: FeedStatus;
  retry: () => void;
  markAllRead: () => void;
  clearAll: () => void;
  dismiss: (id: string) => void;
}

/**
 * The notification centre's data (spec 9): jobs of the last day, newest first (the list is sorted oldest first by
 * default and would drop the newest above the limit), the printers with their statuses, and the sheets, turned into
 * entries by `deriveNotifications`; plus the per-browser read/clear/dismiss state. The queries sit under the keys the
 * live events invalidate, so the entries follow the stream without any wiring of their own.
 */
export function useNotifications(): Feed {
  const sheetsOn = useFeature("sheets");
  const store = notificationStore();
  const state = useSyncExternalStore(store.subscribe, store.get);

  const jobs = useQuery({
    queryKey: notificationJobsKey,
    queryFn: () => {
      const since = new Date(Date.now() - WINDOW_MS).toISOString();
      return apiFetch<Job[]>(`/api/v1/jobs${queryString({ since, limit: JOB_LIMIT, order: "newest" })}`);
    },
  });
  const printers = usePrinters();
  const statusResults = useQueries({ queries: (printers.data ?? []).map((p) => printerStatusQuery(p.id)) });
  const sheets = useSheets({}, sheetsOn);
  // The hub's notices (a sheet type marked verified or updated). A failed read is no feed error: the bell
  // then simply has none of them.
  const notices = useQuery({ queryKey: NOTICES_KEY, queryFn: () => apiFetch<SheetTypeNotice[]>("/api/v1/notices"), enabled: sheetsOn });

  const stamps = statusResults.map((r) => r.dataUpdatedAt).join(",");
  const statuses = useMemo(() => {
    const record: Record<string, PrinterStatus | undefined> = {};
    (printers.data ?? []).forEach((p, i) => (record[p.id] = statusResults[i]?.data));
    return record;
    // `stamps` stands for the results: they are new arrays on every render, their stamps are not.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [printers.data, stamps]);

  // Pure render: "now" is when the newest answer arrived, as the overview always measured it.
  const now = Math.max(jobs.dataUpdatedAt, printers.dataUpdatedAt, sheets.dataUpdatedAt, ...statusResults.map((r) => r.dataUpdatedAt));

  const entries = useMemo(
    () =>
      [
        ...deriveNotifications({
          jobs: jobs.data ?? [],
          printers: printers.data ?? [],
          statuses,
          sheets: sheetsOn ? (sheets.data ?? []) : [],
          firstSeen: state.firstSeen,
          now,
        }),
        // Joined after the derivation: outside its 100-entry cap and its standing rule.
        ...deriveNotices(sheetsOn ? (notices.data ?? []) : []),
      ].sort(newestFirst),
    [jobs.data, printers.data, statuses, sheets.data, sheetsOn, notices.data, state.firstSeen, now],
  );

  // A condition's time is the moment this browser first saw it. Only kinds whose source has been read are tracked,
  // so a source that is still loading (or failed) cannot make the times of its conditions start over.
  const printersRead = printers.isSuccess && statusResults.every((r) => !r.isPending);
  const sheetsRead = sheetsOn && sheets.isSuccess;
  useEffect(() => {
    const kinds: Notification["kind"][] = [];
    if (printersRead) kinds.push("printer");
    if (sheetsRead) kinds.push("sheet");
    if (kinds.length > 0) store.update((s) => trackFirstSeen(s, entries, kinds));
  }, [entries, printersRead, sheetsRead, store]);

  const visible = useMemo(() => entries.filter((e) => isVisible(e, state)), [entries, state]);
  const badge = useMemo(() => badgeOf(entries, state), [entries, state]);

  const sources = [jobs, printers, ...(sheetsOn ? [sheets] : [])];
  const status: FeedStatus = sources.every((q) => q.isError) ? "error" : sources.some((q) => q.isPending) && entries.length === 0 ? "loading" : "ready";

  const refetch = jobs.refetch;
  const refetchPrinters = printers.refetch;
  const refetchSheets = sheets.refetch;
  const refetchNotices = notices.refetch;
  const retry = useCallback(() => {
    void refetch();
    void refetchPrinters();
    if (sheetsOn) {
      void refetchSheets();
      void refetchNotices();
    }
  }, [refetch, refetchPrinters, refetchSheets, refetchNotices, sheetsOn]);

  return {
    entries,
    visible,
    state,
    badge,
    status,
    retry,
    markAllRead: () => store.update((s) => markAllRead(s, visible)),
    clearAll: () => store.update((s) => clearAll(s, entries)),
    dismiss: (id) => store.update((s) => dismiss(s, id)),
  };
}

/** The unresolved errors and warnings that were neither cleared nor dismissed: the overview's "Needs attention". */
export function useAttention(): Pick<Feed, "dismiss" | "status"> & { entries: Notification[] } {
  const feed = useNotifications();
  const entries = useMemo(() => feed.visible.filter((e) => !e.resolved && (e.severity === "error" || e.severity === "warning")), [feed.visible]);
  return { entries, dismiss: feed.dismiss, status: feed.status };
}
