import { msg } from "@lingui/core/macro";
import { i18n } from "@lingui/core";
import { apiFetch } from "../../api/client";
import { jobTitle } from "../jobs/model";
import type { Job } from "../jobs/api";
import type { SearchSource } from "./registry";

/** A job id is a UUID; three hex digits are enough to mean one, a word is not a job. */
const ID_PREFIX = /^[0-9a-f-]{3,}$/i;
const SEARCH_LIMIT = 50;

/**
 * Jobs by the start of their id, from the latest 50. The key sits under `["jobs"]`, so a job
 * event refreshes it; within a few seconds typing again reuses the answer.
 */
export const jobsSource: SearchSource = {
  id: "jobs",
  order: 20,
  async search(query, { queryClient }) {
    const q = query.trim().toLowerCase();
    if (!ID_PREFIX.test(q)) return [];
    const jobs = await queryClient.fetchQuery({
      queryKey: ["jobs", "search"],
      queryFn: () => apiFetch<Job[]>(`/api/jobs?limit=${SEARCH_LIMIT}`),
      staleTime: 5_000,
    });
    const group = i18n._(msg`Jobs`);
    return jobs
      .filter((j) => j.id.startsWith(q))
      .map((j) => {
        const code = j.id.slice(0, 8);
        return { id: j.id, group, title: `${jobTitle(j) ?? code} ${code}`.trim(), code, detail: j.state, href: `/jobs/${j.id}` };
      });
  },
};
