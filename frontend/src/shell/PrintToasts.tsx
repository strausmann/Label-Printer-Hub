import { plural } from "@lingui/core/macro";
import { useLingui } from "@lingui/react/macro";
import { Link } from "@tanstack/react-router";
import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { useJob, useRetryJob } from "../features/jobs/api";
import { canRetry } from "../features/jobs/model";
import {
  dismissWatch,
  replaceWatchedJob,
  useWatchedPrints,
  type JobLive,
  type JobPhase,
  type PrintKind,
  type WatchedPrint,
} from "../features/jobs/printWatch";
import { RetryError } from "../features/jobs/RetryError";
import { usePrinters } from "../features/printers/api";
import { CloseIcon } from "./icons";

/** A finished print leaves by itself after this long; a failed one stays until it is closed. */
export const AUTO_DISMISS_MS = 5_000;
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

/** The state in words, with the jobs ahead and the page job's place at the printer where the events say so. */
function useStateWords(): (phase: JobPhase, live: JobLive | undefined) => string {
  const { t } = useLingui();
  return (phase, live) => {
    switch (phase) {
      case "queued": {
        // `queue_depth` counts the open jobs of the printer, this one included.
        const ahead = Math.max(0, (live?.queueDepth ?? 0) - 1);
        return ahead > 0 ? plural(ahead, { one: "Queued, # job ahead", other: "Queued, # jobs ahead" }) : t`Queued`;
      }
      case "printing":
        if (live?.atPrinter === "waiting") return t`Waiting at the printer`;
        if (live?.atPrinter === "stopped") return t`Stopped at the printer`;
        return t`Printing`;
      case "done":
        return t`Done`;
      case "failed":
        return t`Failed`;
      case "cancelled":
        return t`Cancelled`;
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

/** The reason and the way out for a failed print: the job's own words, Retry where the hub allows it. */
function Failure({ entry }: { entry: WatchedPrint }) {
  const { t } = useLingui();
  const jobId = entry.failedJobIds[0]!;
  const job = useJob(jobId);
  const retry = useRetryJob();
  return (
    <div className="mt-2 flex flex-col gap-2">
      <p className="text-small [overflow-wrap:anywhere]">{job.data?.error ?? t`The printer or the hub reported an error.`}</p>
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
            onClick={() => retry.mutate(jobId, { onSuccess: (created) => replaceWatchedJob(entry.id, jobId, created.id) })}
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
            {stateWords(entry.phase, live)}
            {progress && <span className="tabular-nums"> · {progress}</span>}
          </p>
          {entry.total > 1 && (
            <div aria-hidden="true" className="mt-2 h-1.5 overflow-hidden rounded-full bg-sunken">
              <div
                className="h-full origin-left rounded-full bg-ok transition-transform duration-200 ease-out"
                style={{ transform: `scaleX(${entry.finished / entry.total})` }}
              />
            </div>
          )}
          {failed && <Failure entry={entry} />}
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
  const failed = entries.filter((e) => e.phase === "failed");
  const rest = entries.filter((e) => e.phase !== "failed");
  return (
    <section
      aria-label={t`Print status`}
      className="pointer-events-none fixed inset-x-4 bottom-[calc(7.5rem+env(safe-area-inset-bottom))] z-30 flex flex-col gap-2 lg:inset-x-auto lg:right-6 lg:bottom-6 lg:w-96"
    >
      <ul aria-live="assertive" aria-relevant="additions text" className="m-0 flex list-none flex-col gap-2 p-0">
        {failed.map((entry) => (
          <Card key={entry.id} entry={entry} />
        ))}
      </ul>
      <ul aria-live="polite" aria-relevant="additions text" className="m-0 flex list-none flex-col gap-2 p-0">
        {rest.map((entry) => (
          <Card key={entry.id} entry={entry} />
        ))}
      </ul>
    </section>
  );
}
