// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useLingui } from "@lingui/react/macro";
import { Link } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { StatusBadge } from "../../shell/StatusBadge";
import { useJob, useRetryJob } from "../jobs/api";
import { useJobErrorText } from "../jobs/jobErrorText";
import { badgeOf, useStateWords } from "../jobs/liveText";
import { canRetry } from "../jobs/model";
import {
  claimJob,
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

interface PrintResultProps {
  /** The job the print queued, or null before any print (the region is there, empty). */
  jobId: string | null;
  printerId: string;
  /** What the print is, for the line: "Calibration page". */
  subject: string;
  /** The accessible name of the live region. */
  label: string;
  /** The next step once the page is out of the printer. */
  doneHint: string;
}

/**
 * The line under a print button. The live region is always in the page (empty until a print was queued), so
 * the line appears without moving anything and a screen reader announces what is written into it. It holds
 * ONLY the status sentence; the links and Retry sit beside it, so a state change does not re-read them. It
 * sits outside the button row: a sentence in the row wrapped under the primary button and pushed the others.
 *
 * It reads the job from the same store as the notification stack (`useJobLive`), so the two always agree, and
 * it claims the job so the stack shows its card without announcing it a second time.
 */
export function PrintResult({ jobId: firstJobId, printerId, subject, label, doneHint }: PrintResultProps) {
  const { t } = useLingui();
  const stateWords = useStateWords();
  // The print was registered with the stack by the mutation hook; the stack's entry decides which job is current.
  const [own, setOwn] = useState(() => ({ entryId: firstJobId ? (watchedPrintOfJob(firstJobId)?.id ?? null) : null, jobId: firstJobId }));
  const entry = useWatchedPrints().find((p) => p.id === own.entryId);
  const entryJob = entry?.jobIds[0];
  // The stack retried it: follow (state adjusted while rendering, like the form drafts on this page).
  if (entryJob && entryJob !== own.jobId) setOwn({ entryId: own.entryId, jobId: entryJob });
  const jobId = entryJob ?? own.jobId;
  const live = useJobLive(jobId);
  const phase = live?.phase ?? "queued";

  // Claim the job while this line shows it: the stack stops announcing it, and a reconnect still resyncs it
  // when its card was dismissed.
  useEffect(() => (jobId ? claimJob(jobId) : undefined), [jobId]);

  const mounted = useRef(false);
  useEffect(() => {
    mounted.current = true;
    return () => void (mounted.current = false);
  }, []);

  const retried = (newJobId: string) => {
    let entryId = own.entryId;
    if (entry) replaceWatchedJob(entry.id, jobId!, newJobId);
    // `retried` also runs from the retry's answer after this line is gone; then nobody will claim the new job.
    else entryId = watchPrint({ kind: "calibration", printerId, jobIds: [newJobId], claimPending: mounted.current });
    setOwn({ entryId, jobId: newJobId });
  };

  return (
    <div className="flex min-h-11 flex-wrap items-center gap-x-3 gap-y-1 text-small">
      <span role="status" aria-live="polite" aria-label={label} className="inline-flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
        {jobId && (
          <>
            <StatusBadge state={badgeOf(phase, live)} label={stateWords(phase, live)} />
            {phase === "failed" ? (
              <FailedWords jobId={jobId} live={live} />
            ) : (
              <span className="min-w-0 [overflow-wrap:anywhere]">{phase === "done" ? doneHint : subject}</span>
            )}
          </>
        )}
      </span>
      {jobId && (
        <>
          {phase === "failed" && <FailedActions jobId={jobId} onRetried={retried} />}
          <Link to="/jobs/$jobId" params={{ jobId }} className={LINK}>
            {t`Show the job`}
          </Link>
        </>
      )}
    </div>
  );
}

/** The reason in the app's words, from the error code of the event or the prefix of the job record's message. */
function FailedWords({ jobId, live }: { jobId: string; live: JobLive | undefined }) {
  const errorText = useJobErrorText();
  const job = useJob(jobId);
  const code = live?.errorCode ?? errorCodeFromMessage(job.data?.error);
  return <span className="min-w-0 font-bold text-bad [overflow-wrap:anywhere]">{errorText(code)}</span>;
}

function FailedActions({ jobId, onRetried }: { jobId: string; onRetried: (newJobId: string) => void }) {
  const { t } = useLingui();
  const job = useJob(jobId);
  const retry = useRetryJob();
  return (
    <>
      {job.data && canRetry(job.data) && (
        <button
          type="button"
          className={BUTTON}
          disabled={retry.isPending}
          onClick={(event) => {
            event.currentTarget.blur();
            // mutateAsync: the answer is used even if this part is gone by then (the stack retried first).
            // A second press elsewhere (the stack) joins this request: one clone, not two.
            retry.mutateAsync(jobId).then((created) => onRetried(created.id), () => undefined);
          }}
        >
          {t`Retry`}
        </button>
      )}
      {retry.isError && (
        <span role="alert" className="basis-full text-bad [overflow-wrap:anywhere]">
          <RetryError error={retry.error} sheetCode={null} />
        </span>
      )}
    </>
  );
}
