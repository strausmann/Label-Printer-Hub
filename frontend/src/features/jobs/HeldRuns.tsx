import { plural } from "@lingui/core/macro";
import { useLingui } from "@lingui/react/macro";
import { usePrinters } from "../printers/api";
import { SECONDARY_BUTTON, SECTION_HEADING } from "../ui";
import { useHeldRuns, type TapeRunRead } from "./api";
import { RunControls, type RunControlState } from "./RunControls";

/** The API's run in the shape the controls take. */
export function controlStateOf(run: TapeRunRead): RunControlState {
  return {
    batchId: run.batch_id,
    waiting: run.state === "awaiting_confirmation",
    subJob: run.current_sub_job,
    subJobs: run.sub_jobs,
    stopKind: run.stop_kind,
    unknownFrom: run.unknown_from,
    unknownTo: run.unknown_to,
    reprintFrom: run.reprint_from,
    reprintTo: run.reprint_to,
    stopCode: run.stop_kind === "unknown" ? "outcome_unknown" : run.stop_code,
    total: run.job_ids.length,
  };
}

/**
 * Tape batches that wait for the user (#277): a part waits for a confirmation, or a run stopped. They stay here
 * with their actions after the notification is closed or the page reloaded; nothing is shown when none waits.
 */
export function HeldRuns() {
  const { t } = useLingui();
  const runs = useHeldRuns();
  const printers = usePrinters();
  if (!runs.data || runs.data.length === 0) return null;
  const printerName = (id: string) => printers.data?.find((p) => p.id === id)?.name ?? t`Unknown printer`;
  return (
    <section aria-labelledby="held-runs-h" className="flex flex-col gap-3">
      <h2 id="held-runs-h" className={SECTION_HEADING}>{t`Tape prints that wait for you`}</h2>
      <ul className="m-0 flex list-none flex-col gap-2 p-0">
        {runs.data.map((run) => {
          const name = printerName(run.printer_id);
          const labels = run.job_ids.length;
          return (
            <li key={run.batch_id} className="rounded-r3 border border-line-strong bg-surface px-4 py-3">
              <p className="font-bold [overflow-wrap:anywhere]">
                {plural(labels, { one: `# label on ${name}`, other: `# labels on ${name}` })}
              </p>
              <p className="text-small text-ink-2">{run.state === "stopped" ? t`Stopped` : t`Waiting for you`}</p>
              <RunControls run={controlStateOf(run)} buttonClass={SECONDARY_BUTTON} idPrefix={`held-${run.batch_id}`} />
            </li>
          );
        })}
      </ul>
    </section>
  );
}
