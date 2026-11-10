import { useLingui } from "@lingui/react/macro";
import { Link } from "@tanstack/react-router";
import { useState, type ReactNode } from "react";
import { StatusBadge } from "../../shell/StatusBadge";
import { useJob, useRetryJob } from "../jobs/api";
import { useJobErrorText } from "../jobs/jobErrorText";
import { badgeOf, useStateWords } from "../jobs/liveText";
import { canRetry } from "../jobs/model";
import {
  errorCodeFromMessage,
  replaceWatchedJob,
  useJobLive,
  useWatchedPrints,
  watchedPrintOfJob,
  watchPrint,
  type JobLive,
} from "../jobs/printWatch";
import { RetryError } from "../jobs/RetryError";

const BUTTON =
  "press inline-flex min-h-11 items-center justify-center rounded-r2 border border-line-strong bg-surface px-3 text-small font-bold text-ink focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-link disabled:opacity-60 [@media(hover:hover)]:hover:bg-sunken";
const LINK = "inline-flex min-h-11 items-center text-small font-bold text-link underline underline-offset-2";

/**
 * The live region under a print button. It is always in the page (empty until a print was queued), so the
 * line appears without moving anything and a screen reader announces what is written into it. It sits
 * OUTSIDE the button row: a sentence in the row wrapped under the primary button and pushed the others.
 */
export function PrintResultRegion({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div role="status" aria-live="polite" aria-label={label} className="min-h-11 text-small">
      {children}
    </div>
  );
}

interface PrintResultProps {
  /** The job the print queued. */
  jobId: string;
  printerId: string;
  /** What the print is, for the line: "Calibration page". */
  subject: string;
  /** The next step once the page is out of the printer. */
  doneHint: string;
}

/**
 * Where the page just sent stands, read from the same store as the notification stack (`useJobLive`),
 * so the two always agree. A retry from this line or from the stack moves both to the new job.
 */
export function PrintResult({ jobId: firstJobId, printerId, subject, doneHint }: PrintResultProps) {
  const { t } = useLingui();
  const stateWords = useStateWords();
  // The print was registered with the stack by the mutation hook; the stack's entry decides which job is current.
  const [own, setOwn] = useState(() => ({ entryId: watchedPrintOfJob(firstJobId)?.id ?? null, jobId: firstJobId }));
  const entry = useWatchedPrints().find((p) => p.id === own.entryId);
  const entryJob = entry?.jobIds[0];
  // The stack retried it: follow (state adjusted while rendering, like the form drafts on this page).
  if (entryJob && entryJob !== own.jobId) setOwn({ entryId: own.entryId, jobId: entryJob });
  const jobId = entryJob ?? own.jobId;
  const live = useJobLive(jobId);
  const phase = live?.phase ?? "queued";

  const retried = (newJobId: string) => {
    let entryId = own.entryId;
    if (entry) replaceWatchedJob(entry.id, jobId, newJobId);
    else entryId = watchPrint({ kind: "calibration", printerId, jobIds: [newJobId] });
    setOwn({ entryId, jobId: newJobId });
  };

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
      <StatusBadge state={badgeOf(phase, live)} label={stateWords(phase, live)} />
      {phase === "failed" ? (
        <Failure jobId={jobId} live={live} onRetried={retried} />
      ) : (
        <span className="min-w-0 [overflow-wrap:anywhere]">{phase === "done" ? doneHint : subject}</span>
      )}
      <Link to="/jobs/$jobId" params={{ jobId }} className={LINK}>
        {t`Show the job`}
      </Link>
    </div>
  );
}

function Failure({ jobId, live, onRetried }: { jobId: string; live: JobLive | undefined; onRetried: (newJobId: string) => void }) {
  const { t } = useLingui();
  const errorText = useJobErrorText();
  const job = useJob(jobId);
  const retry = useRetryJob();
  const code = live?.errorCode ?? errorCodeFromMessage(job.data?.error);
  return (
    <>
      <span className="min-w-0 font-bold text-bad [overflow-wrap:anywhere]">{errorText(code)}</span>
      {job.data && canRetry(job.data) && (
        <button
          type="button"
          className={BUTTON}
          disabled={retry.isPending}
          onClick={(event) => {
            event.currentTarget.blur();
            // mutateAsync: the answer is used even if this part is gone by then (the stack retried first).
            retry.mutateAsync(jobId).then((created) => onRetried(created.id), () => undefined);
          }}
        >
          {t`Retry`}
        </button>
      )}
      {retry.isError && (
        <span className="basis-full text-bad [overflow-wrap:anywhere]">
          <RetryError error={retry.error} sheetCode={null} />
        </span>
      )}
    </>
  );
}
