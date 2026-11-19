// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { apiFetch } from "../../api/client";
import { queryString } from "../../api/queryString";
import type { Job } from "../printers/api";

/** Jobs are fetched for this long back; the derivation drops what changed before it too, so a stale answer cannot show old failures. */
export const WINDOW_MS = 24 * 60 * 60 * 1000;

/** Under `["jobs"]`, the prefix every job event invalidates (and the reconnect resync re-reads). */
export const notificationJobsKey = ["jobs", "notifications"] as const;
const JOB_LIMIT = 200;

/**
 * The jobs of the last day, newest first (the list is sorted oldest first by default and would drop the newest above
 * the limit). Read by the notification centre and by `usePrinterWaiting`, so both decide from the same answer.
 */
export const notificationJobsQuery = () => ({
  queryKey: notificationJobsKey,
  queryFn: () => {
    const since = new Date(Date.now() - WINDOW_MS).toISOString();
    return apiFetch<Job[]>(`/api/v1/jobs${queryString({ since, limit: JOB_LIMIT, order: "newest" })}`);
  },
});
