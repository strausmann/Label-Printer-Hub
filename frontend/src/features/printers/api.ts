import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../../api/client";
import type { components } from "../../api/schema.gen";

export type Printer = components["schemas"]["app__schemas__printer__PrinterRead"];
export type PrinterStatus = components["schemas"]["PrinterStatus"];
export type Job = components["schemas"]["JobRead"];

/** `GET /api/printers/{id}/queue` returns loose objects; these are the fields it sets. */
export interface QueueJob {
  id: string;
  printer_id: string;
  template_key: string | null;
  state: string;
  created_at: string;
}

/*
 * Query keys are the ones the live-event hook invalidates (api/events.ts): an event on a
 * printer refreshes `["printers"]` and everything below it, a job event `["jobs"]`.
 */
export const printersKey = ["printers"] as const;
export const printerKey = (id: string) => ["printers", id] as const;
export const statusKey = (id: string) => ["printers", id, "status"] as const;
export const queueKey = (id: string) => ["printers", id, "queue"] as const;
export const jobsKey = ["jobs", "recent"] as const;

export const usePrinters = () =>
  useQuery({ queryKey: printersKey, queryFn: () => apiFetch<Printer[]>("/api/printers") });

export const usePrinter = (id: string) =>
  useQuery({ queryKey: printerKey(id), queryFn: () => apiFetch<Printer>(`/api/printers/${id}`) });

export const usePrinterStatus = (id: string, enabled = true) =>
  useQuery({ queryKey: statusKey(id), queryFn: () => apiFetch<PrinterStatus>(`/api/printers/${id}/status`), enabled });

/** One status per printer, keyed by printer id (a failed probe simply has no entry). */
export function usePrinterStatuses(printers: Printer[] | undefined): Map<string, PrinterStatus> {
  const results = useQueries({
    queries: (printers ?? []).map((p) => ({
      queryKey: statusKey(p.id),
      queryFn: () => apiFetch<PrinterStatus>(`/api/printers/${p.id}/status`),
    })),
  });
  const map = new Map<string, PrinterStatus>();
  (printers ?? []).forEach((p, i) => {
    const data = results[i]?.data;
    if (data) map.set(p.id, data);
  });
  return map;
}

export const useQueue = (id: string) =>
  useQuery({ queryKey: queueKey(id), queryFn: () => apiFetch<QueueJob[]>(`/api/printers/${id}/queue`) });

/** The newest jobs of all printers; the overview sorts out running, failed and recent ones. */
export const useRecentJobs = () =>
  useQuery({ queryKey: jobsKey, queryFn: () => apiFetch<Job[]>("/api/jobs?limit=100") });

/** Pause or resume dispatch; the event stream refreshes the rest, this makes it instant. */
export function usePauseResume() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, action }: { id: string; action: "pause" | "resume" }) =>
      apiFetch<void>(`/api/printers/${id}/${action}`, { method: "POST" }),
    onSettled: () => client.invalidateQueries({ queryKey: printersKey }),
  });
}

export function useCancelJob(printerId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) => apiFetch<Job>(`/api/jobs/${jobId}/cancel`, { method: "POST" }),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: queueKey(printerId) });
      void client.invalidateQueries({ queryKey: ["jobs"] });
    },
  });
}

export function useClearQueue(printerId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => apiFetch<void>(`/api/printers/${printerId}/queue/clear`, { method: "POST" }),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: queueKey(printerId) });
      void client.invalidateQueries({ queryKey: ["jobs"] });
    },
  });
}
