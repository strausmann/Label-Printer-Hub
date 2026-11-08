import { useQuery } from "@tanstack/react-query";

/**
 * Where a sheet page job stands at the printer. It reaches the browser only as a live
 * `job.state_changed` event (the job record has no such field), so the event hook stores the
 * latest one per job here and the job views read it back.
 */
export interface PageJobState {
  kind: string;
  /** `waiting` / `printing` / `stopped`, or null when the value is not one the UI knows. */
  atPrinter: "waiting" | "printing" | "stopped" | null;
  reasons: string[];
  summary: string | null;
}

export const pageJobStateKey = (jobId: string) => ["jobs", jobId, "at_printer"] as const;

const AT_PRINTER = new Set(["waiting", "printing", "stopped"]);

/** Reads the page-job part of a `job.state_changed` payload; null for a job without a `kind`. */
export function pageJobStateFrom(data: Record<string, unknown>): { jobId: string; state: PageJobState } | null {
  if (typeof data.job_id !== "string" || typeof data.kind !== "string") return null;
  const reasons = Array.isArray(data.at_printer_reasons) && data.at_printer_reasons.every((r) => typeof r === "string");
  return {
    jobId: data.job_id,
    state: {
      kind: data.kind,
      atPrinter: typeof data.at_printer === "string" && AT_PRINTER.has(data.at_printer) ? (data.at_printer as PageJobState["atPrinter"]) : null,
      reasons: reasons ? (data.at_printer_reasons as string[]) : [],
      summary: typeof data.summary === "string" ? data.summary : null,
    },
  };
}

/**
 * The stored sub-state, or undefined while no event has been seen (a reloaded page): the UI then
 * says "at the printer" without guessing. Never fetches: the entry is written by the event hook.
 */
export const usePageJobState = (jobId: string) =>
  useQuery<PageJobState | undefined>({
    queryKey: pageJobStateKey(jobId),
    queryFn: () => undefined,
    enabled: false,
    staleTime: Infinity,
    gcTime: Infinity,
  }).data;
