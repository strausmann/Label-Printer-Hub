import { useLingui } from "@lingui/react/macro";
import { Link } from "@tanstack/react-router";
import type { ReactNode } from "react";
import { StatusBadge } from "../../shell/StatusBadge";
import { IntegrationTiles } from "../integrations/IntegrationTiles";
import { PANEL, SECTION_HEADING } from "../ui";
import { usePrinters, usePrinterStatuses, useRecentJobs, type Job, type Printer, type PrinterStatus } from "../printers/api";
import { describePrinter, isFailed, useJobStateBadge, useKindLabel } from "../printers/model";
import { PauseReason } from "../printers/PauseReason";
import { PauseResumeButton } from "../printers/PauseResumeButton";
import { PrinterGrid } from "../printers/PrinterGrid";
import { TapeSwatch } from "../printers/TapeSwatch";

/** Measured against when the jobs were fetched (pure render). A failure counts as "needs attention" for a day; older ones live on the Jobs page. */
const ATTENTION_WINDOW_MS = 24 * 60 * 60 * 1000;

function Block({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section aria-labelledby={id} className={`${PANEL} flex flex-col gap-3`}>
      <h2 id={id} className={SECTION_HEADING}>
        {title}
      </h2>
      {children}
    </section>
  );
}

const jobLabel = (job: Job, fallback: string) => job.template_key ?? fallback;

/** The three questions of the spec (5.3): what is printing, what is stuck and why, is material running out. */
export function OverviewPage() {
  const { t } = useLingui();
  const printers = usePrinters();
  const statuses = usePrinterStatuses(printers.data);
  const jobs = useRecentJobs();
  const kinds = useKindLabel();
  const stateOf = useJobStateBadge();

  const list = printers.data ?? [];
  const name = (id: string) => list.find((p) => p.id === id)?.name ?? t`Unknown printer`;
  const all = jobs.data ?? [];
  const running = all.filter((j) => j.state === "printing");
  const busy = new Set(running.map((j) => j.printer_id));
  const failed = all.filter((j) => isFailed(j) && jobs.dataUpdatedAt - Date.parse(j.updated_at) < ATTENTION_WINDOW_MS);
  const stuck = list
    .map((p) => ({ printer: p, view: describePrinter(p, statuses.get(p.id), busy.has(p.id)) }))
    .filter(({ view }) => view.kind === "paused" || view.kind === "offline" || view.kind === "error");
  const recent = [...all].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at)).slice(0, 8);

  return (
    <div className="flex flex-col gap-8">
      <h1 className="text-title font-bold">{t`Overview`}</h1>
      {jobs.isError && <p role="alert" className="text-bad">{t`The jobs could not be loaded.`}</p>}

      <div className="grid gap-4 xl:grid-cols-3">
        <Block id="printing-h" title={t`Printing now`}>
          {running.length === 0 ? (
            <p className="text-ink-2">{t`Nothing is printing.`}</p>
          ) : (
            <ul className="flex flex-col gap-3">
              {running.map((job) => (
                <li key={job.id} className="flex flex-col gap-1">
                  <Link to="/jobs/$jobId" params={{ jobId: job.id }} className="font-bold text-link underline underline-offset-2">
                    {jobLabel(job, t`Label`)}
                  </Link>
                  <span className="text-small text-ink-2">{name(job.printer_id)}</span>
                </li>
              ))}
            </ul>
          )}
        </Block>

        <Block id="attention-h" title={t`Needs attention`}>
          {stuck.length === 0 && failed.length === 0 ? (
            <p className="text-ink-2">{t`Nothing needs attention.`}</p>
          ) : (
            <ul className="flex flex-col gap-4">
              {stuck.map(({ printer, view }) => (
                <li key={printer.id} className="flex flex-col items-start gap-2">
                  <span className="font-bold">{printer.name}</span>
                  <StatusBadge state={view.badge} label={kinds[view.kind]} />
                  {view.detail && <span className="text-small text-ink-2">{view.detail}</span>}
                  {view.kind === "paused" && <PauseReason pause={printer.pause} />}
                  {view.kind === "paused" && <PauseResumeButton printer={printer} named />}
                </li>
              ))}
              {failed.map((job) => {
                const state = stateOf(job.state);
                return (
                  <li key={job.id} className="flex flex-col items-start gap-1">
                    <Link to="/jobs/$jobId" params={{ jobId: job.id }} className="font-bold text-link underline underline-offset-2">
                      {jobLabel(job, t`Label`)}
                    </Link>
                    <StatusBadge state={state.badge} label={state.label} />
                    <span className="text-small text-ink-2">{name(job.printer_id)}</span>
                    {job.error && <span className="text-small">{job.error}</span>}
                  </li>
                );
              })}
            </ul>
          )}
        </Block>

        <IntegrationTiles />

        <Block id="material-h" title={t`Material`}>
          {list.length === 0 ? (
            <p className="text-ink-2">{t`No printers yet.`}</p>
          ) : (
            <ul className="flex flex-col gap-3">
              {list.map((p) => (
                <MaterialRow key={p.id} printer={p} status={statuses.get(p.id)} />
              ))}
            </ul>
          )}
        </Block>
      </div>

      <section aria-labelledby="printers-h" className="flex flex-col gap-3">
        <h2 id="printers-h" className={SECTION_HEADING}>{t`Printers`}</h2>
        <PrinterGrid />
      </section>

      <section aria-labelledby="recent-h" className="flex flex-col gap-3">
        <h2 id="recent-h" className={SECTION_HEADING}>{t`Recent jobs`}</h2>
        {recent.length === 0 ? (
          <p className="text-ink-2">{t`No jobs yet.`}</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {recent.map((job) => {
              const state = stateOf(job.state);
              return (
                <li key={job.id} className={`${PANEL} flex flex-wrap items-center justify-between gap-3 py-3`}>
                  <span className="flex min-w-0 flex-col">
                    <Link to="/jobs/$jobId" params={{ jobId: job.id }} className="font-bold text-link underline underline-offset-2">
                      {jobLabel(job, t`Label`)}
                    </Link>
                    <span className="text-small text-ink-2">{name(job.printer_id)}</span>
                  </span>
                  <StatusBadge state={state.badge} label={state.label} />
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}

function MaterialRow({ printer, status }: { printer: Printer; status: PrinterStatus | undefined }) {
  return (
    <li className="flex flex-col gap-1">
      <span className="text-small text-ink-2">{printer.name}</span>
      <TapeSwatch tapeLoaded={status?.tape_loaded} probed={status?.captured_at != null} />
    </li>
  );
}
