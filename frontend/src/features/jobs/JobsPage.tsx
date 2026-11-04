import { useLingui } from "@lingui/react/macro";
import { Link } from "@tanstack/react-router";
import { useState } from "react";
import { ToggleButton, ToggleButtonGroup } from "react-aria-components";
import { StatusBadge } from "../../shell/StatusBadge";
import { usePrinters } from "../printers/api";
import { useJobStateBadge } from "../printers/model";
import { useJobs } from "./api";
import { formatTime, jobTitle, JOB_FILTERS, type JobFilter } from "./model";

const CHIP =
  "press inline-flex h-11 items-center rounded-r2 border border-line-strong px-4 text-small font-bold text-ink hover:bg-sunken data-[selected]:border-ink data-[selected]:bg-ink data-[selected]:text-bg data-[focus-visible]:outline-3 data-[focus-visible]:outline-offset-2 data-[focus-visible]:outline-link";

function useFilterLabels(): Record<JobFilter, string> {
  const { t } = useLingui();
  return { all: t`All`, queued: t`Queued`, printing: t`Printing`, done: t`Done`, failed: t`Failed`, cancelled: t`Cancelled` };
}

export function JobsPage() {
  const { t } = useLingui();
  const [filter, setFilter] = useState<JobFilter>("all");
  const labels = useFilterLabels();
  const stateOf = useJobStateBadge();
  const jobs = useJobs(filter === "all" ? null : filter);
  const printers = usePrinters();
  const printerName = (id: string) => printers.data?.find((p) => p.id === id)?.name ?? t`Unknown printer`;
  // The API does not promise an order; the newest job comes first.
  const sorted = [...(jobs.data ?? [])].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at));

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-title font-bold">{t`Jobs`}</h1>
      <ToggleButtonGroup
        aria-label={t`Filter by state`}
        selectionMode="single"
        disallowEmptySelection
        selectedKeys={[filter]}
        onSelectionChange={(keys) => {
          const next = [...keys][0];
          if (JOB_FILTERS.some((f) => f === next)) setFilter(next as JobFilter);
        }}
        className="-mx-4 flex gap-2 overflow-x-auto px-4 pb-1 md:mx-0 md:flex-wrap md:px-0"
      >
        {JOB_FILTERS.map((f) => (
          <ToggleButton key={f} id={f} className={CHIP}>
            {labels[f]}
          </ToggleButton>
        ))}
      </ToggleButtonGroup>

      {jobs.isPending && <p role="status" className="text-ink-2">{t`Loading…`}</p>}
      {jobs.isError && <p role="alert" className="text-bad">{t`The jobs could not be loaded.`}</p>}
      {jobs.data && sorted.length === 0 && <p className="text-ink-2">{t`No jobs.`}</p>}
      {sorted.length > 0 && (
        <ul aria-label={t`Jobs`} className="flex flex-col gap-2">
          {sorted.map((job) => {
            const state = stateOf(job.state);
            return (
              <li
                key={job.id}
                className="grid gap-x-4 gap-y-1 rounded-r3 border border-line bg-surface px-4 py-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center"
              >
                <span className="flex min-w-0 flex-col">
                  <Link
                    to="/jobs/$jobId"
                    params={{ jobId: job.id }}
                    className="truncate font-bold text-link underline underline-offset-2"
                  >
                    {jobTitle(job) ?? t`Label`}
                  </Link>
                  <span className="truncate text-small text-ink-2">
                    {printerName(job.printer_id)} · {formatTime(job.created_at)}
                  </span>
                </span>
                <StatusBadge state={state.badge} label={state.label} />
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
