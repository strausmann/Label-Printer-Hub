import { useLingui } from "@lingui/react/macro";
import { useState } from "react";
import { useContinueBatch, useDiscardBatch, useReprintBatch, type ReprintResponse } from "./api";
import { useJobErrorText } from "./jobErrorText";

/** What the controls need to know about a held tape run (#277), from the event stack or from the API. */
export interface RunControlState {
  batchId: string;
  waiting: boolean;
  /** The part that waits (1-based) and how many there are. */
  subJob: number;
  subJobs: number;
  stopKind: "unknown" | "refused" | null;
  /** The unknown group (1-based), when the outcome is unknown. */
  unknownFrom: number | null;
  unknownTo: number | null;
  /** The labels a reprint may start from; for a refused group only its first label. */
  reprintFrom: number | null;
  reprintTo: number | null;
  /** Why it stopped: a job error code (the reason in the app's words). */
  stopCode: string | null;
  total: number;
}

export interface RunControlsProps {
  run: RunControlState;
  buttonClass: string;
  /** A stable id prefix for the select's label. */
  idPrefix: string;
  onContinued?: (subJob: number) => void;
  onReprinted?: (answer: ReprintResponse) => void;
  onDiscarded?: () => void;
}

/**
 * The actions of a held tape run (#277): continue with the next part, reprint from the first missing label
 * after a stop, or give the rest up. Used by the print status stack and by the held-runs list of the jobs page,
 * so closing a notification never loses them.
 */
export function RunControls({ run, buttonClass, idPrefix, onContinued, onReprinted, onDiscarded }: RunControlsProps) {
  const { t } = useLingui();
  const errorText = useJobErrorText();
  const go = useContinueBatch();
  const reprint = useReprintBatch();
  const discard = useDiscardBatch();
  const from = run.reprintFrom ?? 1;
  const to = run.reprintTo ?? from;
  const [pick, setPick] = useState(from);
  const choice = Math.min(Math.max(pick, from), to);
  const busy = go.isPending || reprint.isPending || discard.isPending;
  const failed = go.isError || reprint.isError || discard.isError;
  const total = run.total;
  const selectId = `${idPrefix}-first-missing`;

  const blurThen = (action: () => void) => (event: { currentTarget: HTMLButtonElement }) => {
    // The card changes under the button: focus would otherwise hold it open.
    event.currentTarget.blur();
    action();
  };
  const discardButton = (
    <button type="button" className={buttonClass} disabled={busy} onClick={blurThen(() => discard.mutate(run.batchId, { onSuccess: () => onDiscarded?.() }))}>
      {run.waiting ? t`Discard the rest` : t`Discard`}
    </button>
  );

  if (run.waiting) {
    const done = run.subJob - 1;
    const next = run.subJob;
    const parts = run.subJobs;
    return (
      <div className="mt-2 flex flex-col gap-2">
        <p className="text-small [overflow-wrap:anywhere]">{t`Part ${done} of ${parts} is done. Check the tape, then continue.`}</p>
        {failed && <p className="text-small text-bad">{t`That did not work. Try again.`}</p>}
        <div className="flex flex-wrap gap-2">
          <button type="button" className={buttonClass} disabled={busy} onClick={blurThen(() => go.mutate(run.batchId, { onSuccess: () => onContinued?.(next) }))}>
            {t`Continue with part ${next}`}
          </button>
          {discardButton}
        </div>
      </div>
    );
  }

  const reprintButton = (label: string) => (
    <button
      type="button"
      className={buttonClass}
      disabled={busy}
      onClick={blurThen(() => reprint.mutate({ batchId: run.batchId, fromLabel: choice }, { onSuccess: (answer) => onReprinted?.(answer) }))}
    >
      {label}
    </button>
  );

  if (run.stopKind === "refused") {
    const reason = errorText(run.stopCode);
    return (
      <div className="mt-2 flex flex-col gap-2">
        <p className="text-small [overflow-wrap:anywhere]">{t`Nothing from label ${from} on was sent, so none of them printed. ${reason}`}</p>
        {failed && <p className="text-small text-bad">{t`That did not work. Try again.`}</p>}
        <div className="flex flex-wrap gap-2">
          {reprintButton(t`Print labels ${from} to ${total} again`)}
          {discardButton}
        </div>
      </div>
    );
  }

  const unknownFrom = run.unknownFrom ?? from;
  const unknownTo = run.unknownTo ?? to - 1;
  const options = Array.from({ length: to - from + 1 }, (_, i) => from + i);
  return (
    <div className="mt-2 flex flex-col gap-2">
      <p className="text-small [overflow-wrap:anywhere]">
        {t`Labels ${unknownFrom} to ${unknownTo} may or may not have printed. Count them on the tape, put in a new tape, then reprint from the first label that is missing.`}
      </p>
      {failed && <p className="text-small text-bad">{t`That did not work. Try again.`}</p>}
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
                {n === unknownTo + 1 ? t`${n} (all of ${unknownFrom} to ${unknownTo} printed)` : String(n)}
              </option>
            ))}
          </select>
        </label>
        {reprintButton(t`Reprint from label ${choice}`)}
        {discardButton}
      </div>
    </div>
  );
}
