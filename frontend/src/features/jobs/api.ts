import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../../api/client";
import type { Job } from "../printers/api";

export type { Job };

/*
 * Every key starts with `["jobs"]`, the prefix the live-event hook invalidates, so a job
 * event refreshes the list and the open job without any extra wiring.
 */
export const jobsListKey = (state: string | null) => ["jobs", "list", state ?? "all"] as const;
export const jobKey = (id: string) => ["jobs", id] as const;

export const JOB_LIMIT = 100;

export function useJobs(state: string | null) {
  const query = new URLSearchParams({ limit: String(JOB_LIMIT) });
  if (state) query.set("state", state);
  return useQuery({ queryKey: jobsListKey(state), queryFn: () => apiFetch<Job[]>(`/api/jobs?${query}`) });
}

export const useJob = (id: string) =>
  useQuery({ queryKey: jobKey(id), queryFn: () => apiFetch<Job>(`/api/jobs/${id}`) });

/** Refreshes every job view and the printer queues they feed. */
function useRefreshJobs() {
  const client = useQueryClient();
  return () => {
    void client.invalidateQueries({ queryKey: ["jobs"] });
    void client.invalidateQueries({ queryKey: ["printers"] });
  };
}

/** Retry clones the job into a new queued one; the answer is that new job. */
export function useRetryJob() {
  const refresh = useRefreshJobs();
  return useMutation({
    mutationFn: (id: string) => apiFetch<Job>(`/api/jobs/${id}/retry`, { method: "POST" }),
    onSettled: refresh,
  });
}

export function useCancelJobById() {
  const refresh = useRefreshJobs();
  return useMutation({
    mutationFn: (id: string) => apiFetch<Job>(`/api/jobs/${id}/cancel`, { method: "POST" }),
    onSettled: refresh,
  });
}
