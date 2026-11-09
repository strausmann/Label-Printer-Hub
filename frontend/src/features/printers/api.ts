import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch, ApiError } from "../../api/client";
import type { components } from "../../api/schema.gen";

export type Printer = components["schemas"]["app__schemas__printer__PrinterRead"];
export type PrinterStatus = components["schemas"]["PrinterStatus"];
export type Roll = components["schemas"]["RollRead"];
export type RollColour = NonNullable<components["schemas"]["RollColourUpdate"]["colour"]>;
export type Job = components["schemas"]["JobRead"];

/** `GET /api/v1/printers/{id}/queue` returns loose objects; these are the fields it sets. */
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
export const rollKey = (id: string) => ["printers", id, "roll"] as const;
export const queueKey = (id: string) => ["printers", id, "queue"] as const;
export const jobsKey = ["jobs", "recent"] as const;

export const usePrinters = () =>
  useQuery({ queryKey: printersKey, queryFn: () => apiFetch<Printer[]>("/api/v1/printers") });

export const usePrinter = (id: string) =>
  useQuery({ queryKey: printerKey(id), queryFn: () => apiFetch<Printer>(`/api/v1/printers/${id}`) });

export const usePrinterStatus = (id: string, enabled = true) =>
  useQuery({ queryKey: statusKey(id), queryFn: () => apiFetch<PrinterStatus>(`/api/v1/printers/${id}/status`), enabled });

/** One status per printer, keyed by printer id (a failed probe simply has no entry). */
export function usePrinterStatuses(printers: Printer[] | undefined): Map<string, PrinterStatus> {
  const results = useQueries({
    queries: (printers ?? []).map((p) => ({
      queryKey: statusKey(p.id),
      queryFn: () => apiFetch<PrinterStatus>(`/api/v1/printers/${p.id}/status`),
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
  useQuery({ queryKey: queueKey(id), queryFn: () => apiFetch<QueueJob[]>(`/api/v1/printers/${id}/queue`) });

/** The newest jobs of all printers; the overview sorts out running, failed and recent ones. */
export const useRecentJobs = () =>
  useQuery({ queryKey: jobsKey, queryFn: () => apiFetch<Job[]>("/api/v1/jobs?limit=100") });

/** Pause or resume dispatch; the event stream refreshes the rest, this makes it instant. */
export function usePauseResume() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, action }: { id: string; action: "pause" | "resume" }) =>
      apiFetch<void>(`/api/v1/printers/${id}/${action}`, { method: "POST" }),
    onSettled: () => client.invalidateQueries({ queryKey: printersKey }),
  });
}

export function useCancelJob(printerId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) => apiFetch<Job>(`/api/v1/jobs/${jobId}/cancel`, { method: "POST" }),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: queueKey(printerId) });
      void client.invalidateQueries({ queryKey: ["jobs"] });
    },
  });
}

export function useClearQueue(printerId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => apiFetch<void>(`/api/v1/printers/${printerId}/queue/clear`, { method: "POST" }),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: queueKey(printerId) });
      void client.invalidateQueries({ queryKey: ["jobs"] });
    },
  });
}

/** The recorded roll of a printer: the width and media text the colour question is about. */
export const useRoll = (id: string, enabled = true) =>
  useQuery({ queryKey: rollKey(id), queryFn: () => apiFetch<Roll>(`/api/v1/printers/${id}/roll`), enabled });

/** True for the 409 that says the roll changed after the operator saw the question. */
export const isRollChanged = (error: unknown): boolean =>
  error instanceof ApiError && error.status === 409 && (error.code ?? "").endsWith("roll-changed");

/**
 * Give the roll a colour (or none). The width and media text the operator saw go with it, so a
 * question that went stale while a new roll was inserted answers 409 instead of colouring the
 * new roll. Either way the status and roll are read again.
 */
export function useSetRollColour(printerId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { colour: RollColour | null; width_mm: number | null; media_raw: string | null }) =>
      apiFetch<Roll>(`/api/v1/printers/${printerId}/roll`, { method: "PUT", json: body }),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: statusKey(printerId) });
      void client.invalidateQueries({ queryKey: rollKey(printerId) });
    },
  });
}
