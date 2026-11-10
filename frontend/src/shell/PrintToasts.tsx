import { plural } from "@lingui/core/macro";
import { useLingui } from "@lingui/react/macro";
import { Link } from "@tanstack/react-router";
import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { useContinueBatch, useJob, useReprintBatch, useRetryJob } from "../features/jobs/api";
import { useJobErrorText } from "../features/jobs/jobErrorText";
import { useStateWords } from "../features/jobs/liveText";
import { canRetry } from "../features/jobs/model";
import {
  dismissWatch,
  errorCodeFromMessage,
  markRunContinued,
  replaceRunJobs,
  replaceWatchedJob,
  useWatchedPrints,
  type PrintKind,
  type WatchedPrint,
} from "../features/jobs/printWatch";
import { RetryError } from "../features/jobs/RetryError";
import { usePrinters } from "../features/printers/api";
import { CloseIcon } from "./icons";

/** A finished print leaves by itself after this long; a failed one stays until it is closed. */
export const AUTO_DISMISS_MS = 5_000;
/** At most this many cards show; the rest is one summary line (closing a card brings the next one up). */
export const MAX_VISIBLE = 3;
/** A drag this far (px), or this fast (px/ms), dismisses (the Sonner thresholds). */
const SWIPE_DISTANCE = 80;
const SWIPE_VELOCITY = 0.11;

const BUTTON =
  "press inline-flex min-h-11 items-center justify-center rounded-r2 border border-line-strong bg-surface px-3 text-small font-bold text-ink hover:bg-sunken focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-link disabled:opacity-60";
const LINK = "inline-flex min-h-11 items-center text-small font-bold text-link underline underline-offset-2";

function useKindTitle(): (kind: PrintKind) => string {
  const { t } = useLingui();
  return (kind) => {
    switch (kind) {
      case "item":
        return t`Label`;
      case "cart":
        return t`Cart`;
      case "sheet":
        return t`Sheet print`;
      case "calibration":
        return t`Calibration page`;
      case "test":
        return t`Test print`;
    }
  };
}

function useProgressWords(): (entry: WatchedPrint) => string | null {
  const { t } = useLingui();
  return (entry) => {
    if (entry.total < 2) return null;
    const { finished, total } = entry;
    return entry.kind === "sheet" ? t`${finished} of ${total} pages` : t`${finished} of ${total} items`;
  };
}

/**
 * The reason and the way out for a failed print: the reason in the app's words (from the error code),
 * Retry for every failed job the hub allows to retry, a link to the first failed job.
 */
function Failure({ entry }: { entry: WatchedPrint }) {
  const { t } = useLingui();
  const errorText = useJobErrorText();
  const jobId = entry.failedJobIds[0]!;
  const job = useJob(jobId);
  const retry = useRetryJob();
  const code = entry.live[jobId]?.errorCode ?? errorCodeFromMessage(job.data?.error);
  const retryAll = async () => {
    // One at a time: each retry clones a job, and the entry follows the new one.
    for (const failed of entry.failedJobIds) {
      try {
        const created = await retry.mutateAsync(failed);
        replaceWatchedJob(entry.id, failed, created.id);
      } catch {
        return; // the refusal is shown below; the rest stays failed
      }
    }
  };
  return (
    <div className="mt-2 flex flex-col gap-2">
      <p className="text-small [overflow-wrap:anywhere]">{errorText(code)}</p>
      {retry.isError && (
        <p className="text-small text-bad [overflow-wrap:anywhere]">
          <RetryError error={retry.error} sheetCode={null} />
        </p>
      )}
      <div className="flex flex-wrap items-center gap-x-4">
        {job.data && canRetry(job.data) && (
          <button
            type="button"
            className={BUTTON}
            disabled={retry.isPending}
            onClick={(event) => {
              // The card changes under the button: focus would otherwise hold the finished card open.
              event.currentTarget.blur();
              void retryAll();
            }}
          >
            {t`Retry`}
          </button>
        )}
        <Link to="/jobs/$jobId" params={{ jobId }} className={LINK}>
          {t`Open the job`}
        </Link>
      </div>
    </div>
  );
}

/** #277: the part of a tape batch is done; the next one starts when the user says so (after checking the tape). */
function RunWaits({ entry, batchId }: { entry: WatchedPrint; batchId: string }) {
  const { t } = useLingui();
  const go = useContinueBatch();
  const run = entry.run!;
  const done = run.subJob - 1;
  const next = run.subJob;
  const total = run.subJobs;
  return (
    <div className="mt-2 flex flex-col gap-2">
      <p className="text-small [overflow-wrap:anywhere]">{t`Part ${done} of ${total} is done. Check the tape, then continue.`}</p>
      {go.isError && <p className="text-small text-bad">{t`The next part could not be started. Try again.`}</p>}
      <div>
        <button
          type="button"
          className={BUTTON}
          disabled={go.isPending}
          onClick={(event) => {
            event.currentTarget.blur();
            go.mutate(batchId, { onSuccess: () => markRunContinued(entry.id, next) });
          }}
        >
          {t`Continue with part ${next}`}
        </button>
      </div>
    </div>
  );
}

/**
 * #277: a group of a tape batch failed (the tape ran out, for example). Its labels may or may not have printed:
 * the user counts them, puts in a new tape and reprints from the first missing label. The labels after the group
 * were never sent and come along.
 */
function RunStop({ entry, batchId }: { entry: WatchedPrint; batchId: string }) {
  const { t } = useLingui();
  const reprint = useReprintBatch();
  const run = entry.run!;
  const from = run.unknownFrom!;
  const to = run.unknownTo!;
  const [pick, setPick] = useState(from);
  const choice = Math.min(Math.max(pick, from), to + 1);
  const options = Array.from({ length: to - from + 2 }, (_, i) => from + i);
  const selectId = `run-stop-${entry.id}`;
  return (
    <div className="mt-2 flex flex-col gap-2">
      <p className="text-small [overflow-wrap:anywhere]">
        {t`Labels ${from} to ${to} may or may not have printed. Count them on the tape, put in a new tape, then reprint from the first label that is missing.`}
      </p>
      {reprint.isError && <p className="text-small text-bad">{t`The reprint could not be started. Try again.`}</p>}
      <div className="flex flex-wrap items-end gap-2">
        <label htmlFor={selectId} className="flex flex-col gap-1 text-small font-bold">
          {t`First missing label`}
          <select
            id={selectId}
            value={choice}
            onChange={(event) => setPick(Number(event.target.value))}
            className="min-h-11 rounded-r2 border border-line-strong bg-surface px-2 text-base font-normal tabular-nums text-ink"
          >
            {options.map((n) => (
              <option key={n} value={n}>
                {n === to + 1 ? t`${n} (all of ${from} to ${to} printed)` : String(n)}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          className={BUTTON}
          disabled={reprint.isPending}
          onClick={(event) => {
            event.currentTarget.blur();
            reprint.mutate(
              { batchId, fromLabel: choice },
              {
                onSuccess: (answer) =>
                  replaceRunJobs(entry.id, {
                    jobIds: answer.job_ids,
                    confirmed: answer.confirmed_job_ids,
                    subJobStarts: answer.run?.sub_job_starts ?? [0],
                  }),
              },
            );
          }}
        >
          {t`Reprint from label ${choice}`}
        </button>
      </div>
    </div>
  );
}

function Card({ entry }: { entry: WatchedPrint }) {
  const { t } = useLingui();
  const kindTitle = useKindTitle();
  const stateWords = useStateWords();
  const progressWords = useProgressWords();
  const printers = usePrinters();
  const printerName = printers.data?.find((p) => p.id === entry.printerId)?.name ?? null;
  const [held, setHeld] = useState(false);
  const card = useRef<HTMLLIElement>(null);
  const drag = useRef<{ x: number; at: number; id: number } | null>(null);
  const live = entry.live[entry.jobIds.find((id) => entry.live[id]?.phase === entry.phase) ?? entry.jobIds[0]!];
  const ended = entry.phase === "done" || entry.phase === "cancelled";

  // Auto-dismiss: a finished print goes after a few seconds; hovering or focusing it holds it.
  useEffect(() => {
    if (!ended || held) return;
    const timer = setTimeout(() => dismissWatch(entry.id), AUTO_DISMISS_MS);
    return () => clearTimeout(timer);
  }, [ended, held, entry.id]);

  const dismiss = () => dismissWatch(entry.id);
  const onPointerDown = (event: ReactPointerEvent<HTMLLIElement>) => {
    // Swipe is a touch gesture; a mouse has the close button. Controls inside keep their own taps.
    if (event.pointerType === "mouse" || drag.current || (event.target as HTMLElement).closest("a,button")) return;
    drag.current = { x: event.clientX, at: Date.now(), id: event.pointerId };
    event.currentTarget.setPointerCapture(event.pointerId);
  };
  const onPointerMove = (event: ReactPointerEvent<HTMLLIElement>) => {
    if (!drag.current || drag.current.id !== event.pointerId || !card.current) return;
    card.current.style.transition = "none";
    card.current.style.transform = `translateX(${event.clientX - drag.current.x}px)`;
  };
  const onPointerUp = (event: ReactPointerEvent<HTMLLIElement>) => {
    const start = drag.current;
    if (!start || start.id !== event.pointerId || !card.current) return;
    drag.current = null;
    const dx = event.clientX - start.x;
    const velocity = Math.abs(dx) / Math.max(1, Date.now() - start.at);
    if (Math.abs(dx) >= SWIPE_DISTANCE || velocity > SWIPE_VELOCITY) return dismiss();
    card.current.style.transition = "transform 200ms cubic-bezier(0.23, 1, 0.32, 1)";
    card.current.style.transform = "";
  };

  const title = kindTitle(entry.kind);
  const progress = progressWords(entry);
  const failed = entry.phase === "failed";
  const run = entry.run;
  const batchId = entry.runBatchId;
  const stopped = !!run && run.unknownFrom !== null && !!batchId;
  const waits = !!run && run.awaiting && !!batchId;
  const partNo = run?.subJob ?? 0;
  const parts = run?.subJobs ?? 0;
  const part = parts > 1 && !stopped ? t`Part ${partNo} of ${parts}` : null;
  return (
    // Swipe, hover-hold and Escape are enhancements of the card; the keyboard and screen-reader path is
    // the close button and the links inside it, which are real controls.
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions
    <li
      ref={card}
      data-phase={entry.phase}
      className="print-toast pointer-events-auto touch-pan-y rounded-r3 border border-line-strong bg-surface p-3 shadow-lg"
      onPointerEnter={() => setHeld(true)}
      onPointerLeave={() => setHeld(false)}
      onFocus={() => setHeld(true)}
      onBlur={() => setHeld(false)}
      onKeyDown={(event) => {
        if (event.key === "Escape") dismiss();
      }}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
    >
      <div className="flex items-start gap-3">
        <span
          aria-hidden="true"
          className={`mt-1.5 size-2.5 shrink-0 rounded-full ${failed ? "bg-bad" : entry.phase === "done" ? "bg-ok" : entry.phase === "printing" ? "bg-accent" : "bg-ink-3"}`}
        />
        <div className="min-w-0 flex-1">
          <p className="font-bold [overflow-wrap:anywhere]">
            {title}
            {printerName && <span className="font-normal text-ink-2"> {t`on ${printerName}`}</span>}
          </p>
          <p className={`text-small [overflow-wrap:anywhere] ${failed ? "font-bold text-bad" : "text-ink-2"}`}>
            {waits ? t`Waiting for you` : stopped ? t`Stopped` : stateWords(entry.phase, live)}
            {progress && <span className="tabular-nums"> · {progress}</span>}
            {part && <span className="tabular-nums"> · {part}</span>}
          </p>
          {entry.total > 1 && (
            <div aria-hidden="true" className="mt-2 h-1.5 overflow-hidden rounded-full bg-sunken">
              <div
                className="h-full origin-left rounded-full bg-ok transition-transform duration-200 ease-out"
                style={{ transform: `scaleX(${entry.finished / entry.total})` }}
              />
            </div>
          )}
          {stopped ? <RunStop entry={entry} batchId={batchId} /> : failed ? <Failure entry={entry} /> : null}
          {waits && <RunWaits entry={entry} batchId={batchId} />}
        </div>
        <button
          type="button"
          className="press -m-1.5 inline-flex size-11 shrink-0 items-center justify-center rounded-r2 text-ink-2 focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-link [@media(hover:hover)]:hover:bg-sunken [@media(hover:hover)]:hover:text-ink"
          aria-label={t`Dismiss notification`}
          onClick={dismiss}
        >
          <CloseIcon width={18} height={18} />
        </button>
      </div>
    </li>
  );
}

/**
 * The print status stack, mounted once in the shell so it outlives every page. Progress sits in a polite
 * live region, failures in an assertive one; on a phone the stack rides above the tab bar and its scan button.
 */
export function PrintToasts() {
  const { t } = useLingui();
  const entries = useWatchedPrints();
  // Failures first (they need someone), then the rest, each oldest first; only the first MAX_VISIBLE show.
  const ordered = [...entries.filter((e) => e.phase === "failed"), ...entries.filter((e) => e.phase !== "failed")];
  const shown = ordered.slice(0, MAX_VISIBLE);
  const hidden = ordered.length - shown.length;
  // A print a page shows in its own live line is still a card, but only the page announces it.
  const claimed = shown.filter((e) => e.claimed);
  const failed = shown.filter((e) => !e.claimed && e.phase === "failed");
  const rest = shown.filter((e) => !e.claimed && e.phase !== "failed");
  return (
    // The height is bounded and scrolls inside, so Close and Retry stay reachable on a phone.
    <section
      aria-label={t`Print status`}
      className="pointer-events-none fixed inset-x-4 bottom-[calc(7.5rem+env(safe-area-inset-bottom))] z-30 flex max-h-[calc(100dvh-14rem)] flex-col gap-2 overflow-y-auto overscroll-contain lg:inset-x-auto lg:right-6 lg:bottom-6 lg:max-h-[calc(100dvh-3rem)] lg:w-96"
    >
      <ul aria-live="assertive" aria-relevant="additions text" className="m-0 flex list-none flex-col gap-2 p-0">
        {failed.map((entry) => (
          <Card key={entry.id} entry={entry} />
        ))}
      </ul>
      {claimed.length > 0 && (
        <ul className="m-0 flex list-none flex-col gap-2 p-0">
          {claimed.map((entry) => (
            <Card key={entry.id} entry={entry} />
          ))}
        </ul>
      )}
      <ul aria-live="polite" aria-relevant="additions text" className="m-0 flex list-none flex-col gap-2 p-0">
        {rest.map((entry) => (
          <Card key={entry.id} entry={entry} />
        ))}
        {hidden > 0 && (
          <li className="pointer-events-auto rounded-r3 border border-line-strong bg-surface px-3 py-2 text-small font-bold text-ink-2 shadow-lg">
            {plural(hidden, { one: "# more print notification", other: "# more print notifications" })}
          </li>
        )}
      </ul>
    </section>
  );
}
