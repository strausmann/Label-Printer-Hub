// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { plural } from "@lingui/core/macro";
import { useLingui } from "@lingui/react/macro";
import { Link } from "@tanstack/react-router";
import type { ReactNode } from "react";
import { Button } from "react-aria-components";
import { StatusBadge } from "../../shell/StatusBadge";
import { IntegrationTiles } from "../integrations/IntegrationTiles";
import type { Notification } from "../notifications/derive";
import { useEntryText } from "../notifications/useEntryText";
import { useAttention } from "../notifications/useNotifications";
import { PANEL, SECONDARY_BUTTON, SECTION_HEADING } from "../ui";
import { SheetTiles } from "./SheetTiles";
import { usePrinters, usePrinterStatuses, useRecentJobs, type Job, type Printer, type PrinterStatus } from "../printers/api";
import { formatAge } from "../printers/age";
import { describePrinter, unknownKind, isPagePrinter, tapeWidthOf, useJobStateBadge, useKindLabel } from "../printers/model";
import { MarkerList, noAnswerYet, ReasonLine, runningOut } from "../printers/PageStatus";
import { PauseReason } from "../printers/PauseReason";
import { PauseResumeButton } from "../printers/PauseResumeButton";
import { PrinterGrid } from "../printers/PrinterGrid";
import { TapeSwatch } from "../printers/TapeSwatch";

function Block({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section aria-labelledby={id} className={`${PANEL} flex min-w-0 flex-col gap-3`}>
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
  const stateOf = useJobStateBadge();

  const list = printers.data ?? [];
  const name = (id: string) => list.find((p) => p.id === id)?.name ?? t`Unknown printer`;
  const all = jobs.data ?? [];
  const running = all.filter((j) => j.state === "printing");
  const busy = new Set(running.map((j) => j.printer_id));
  // The same entries as the notification centre: unresolved errors and warnings that were neither cleared nor dismissed.
  const attention = useAttention();
  const lowCount = list.filter((p) => runningOut(statuses.get(p.id))).length;
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
          {attention.entries.length === 0 ? (
            <p className="text-ink-2">{t`Nothing needs attention.`}</p>
          ) : (
            <ul className="flex flex-col gap-4">
              {attention.entries.map((entry) => (
                <AttentionItem
                  key={entry.id}
                  entry={entry}
                  printer={list.find((p) => p.id === entry.target.params.printerId)}
                  status={statuses.get(entry.target.params.printerId ?? "")}
                  busy={busy}
                  onDismiss={() => attention.dismiss(entry.id)}
                />
              ))}
            </ul>
          )}
        </Block>

        <IntegrationTiles />

        <SheetTiles />

        <Block id="material-h" title={t`Material`}>
          {list.length === 0 ? (
            <p className="text-ink-2">{t`No printers yet.`}</p>
          ) : (
            <>
              {lowCount > 0 && (
                <p className="flex items-center gap-2 text-small font-bold">
                  <svg viewBox="0 0 10 10" width="10" height="10" aria-hidden="true" focusable="false" className="shrink-0 fill-current text-warn">
                    <polygon points="5,0 10,5 5,10 0,5" />
                  </svg>
                  {plural(lowCount, { one: "# printer is running out of material", other: "# printers are running out of material" })}
                </p>
              )}
              <ul className="flex flex-col gap-3">
                {list.map((p) => (
                  <MaterialRow key={p.id} printer={p} status={statuses.get(p.id)} />
                ))}
              </ul>
            </>
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

/** One entry of "Needs attention": a printer, a job or a sheet, with what the page can say about it, and Dismiss. */
function AttentionItem({
  entry,
  printer,
  status,
  busy,
  onDismiss,
}: {
  entry: Notification;
  printer: Printer | undefined;
  status: PrinterStatus | undefined;
  busy: Set<string>;
  onDismiss: () => void;
}) {
  const { t, i18n } = useLingui();
  const kinds = useKindLabel();
  const stateOf = useJobStateBadge();
  const text = useEntryText();
  const dismiss = (
    <Button onPress={onDismiss} className={`${SECONDARY_BUTTON} self-start`}>
      {t`Dismiss`}
    </Button>
  );

  if (entry.kind === "printer" && printer && !entry.id.endsWith(":material")) {
    const view = describePrinter(printer, status, busy.has(printer.id));
    const lastAge = status?.last_probe_age_s;
    const ageWord = typeof lastAge === "number" ? formatAge(lastAge, i18n.locale) : "";
    return (
      <li className="flex flex-col items-start gap-2">
        <span className="font-bold">{printer.name}</span>
        <StatusBadge state={view.badge} label={kinds[view.kind]} />
        {view.detail && <span className="text-small text-ink-2">{view.detail}</span>}
        {view.kind === "paused" && <PauseReason pause={printer.pause} />}
        <ReasonLine reasons={view.reasons} />
        {view.kind === "paused" && <PauseResumeButton printer={printer} named />}
        {view.kind === "stale" && typeof lastAge === "number" && (
          <span className="text-small text-ink-2 [overflow-wrap:anywhere]">{t`Last status ${ageWord}`}</span>
        )}
        {dismiss}
      </li>
    );
  }

  if (entry.kind === "job") {
    // The entry id ends in the job's state (`job:<id>:failed`): no second list of jobs is needed to say it.
    const state = stateOf(entry.id.split(":")[2] ?? "");
    return (
      <li className="flex flex-col items-start gap-1">
        <Link to="/jobs/$jobId" params={{ jobId: entry.target.params.jobId ?? "" }} className="font-bold text-link underline underline-offset-2">
          {entry.values.title || t`Label`}
        </Link>
        <StatusBadge state={state.badge} label={state.label} />
        <span className="text-small text-ink-2">{entry.values.printer || t`Unknown printer`}</span>
        {entry.values.error && <span className="text-small">{entry.values.error}</span>}
        {dismiss}
      </li>
    );
  }

  // A sheet, or a printer's supplies: the sentence of the entry, as a link to its page.
  return (
    <li className="flex flex-col items-start gap-2">
      <StatusBadge state={entry.severity === "error" ? "bad" : "warn"} label={entry.severity === "error" ? t`Problem` : t`Warning`} />
      {entry.target.to === "/sheets/$code" ? (
        <Link to="/sheets/$code" params={{ code: entry.target.params.code ?? "" }} className="font-bold text-link underline underline-offset-2 [overflow-wrap:anywhere]">
          {text(entry)}
        </Link>
      ) : (
        <Link to="/printers/$printerId" params={{ printerId: entry.target.params.printerId ?? "" }} className="font-bold text-link underline underline-offset-2 [overflow-wrap:anywhere]">
          {text(entry)}
        </Link>
      )}
      {dismiss}
    </li>
  );
}

function MaterialRow({ printer, status }: { printer: Printer; status: PrinterStatus | undefined }) {
  const { t, i18n } = useLingui();
  const kinds = useKindLabel();
  const page = isPagePrinter(printer, status);
  // The same wording and age as the printer card; a stale or unpolled status shows no tape and no supplies.
  const unknown = unknownKind(status);
  const age = unknown === "stale" ? status?.last_probe_age_s : null;
  const ageWord = typeof age === "number" ? formatAge(age, i18n.locale) : "";
  return (
    <li className="flex min-w-0 flex-col gap-1">
      <span className="break-words text-small text-ink-2">{printer.name}</span>
      {unknown ? (
        <>
          <span className="text-ink-2 [overflow-wrap:anywhere]">{kinds[unknown]}</span>
          {typeof age === "number" && <span className="text-small text-ink-2 [overflow-wrap:anywhere]">{t`Last status ${ageWord}`}</span>}
          <span className="text-ink-2">{page ? t`Supplies not known` : t`Tape not known`}</span>
        </>
      ) : !page ? (
        <TapeSwatch widthMm={tapeWidthOf(status)} colour={status?.tape_colour} probed={status?.captured_at != null} offline={status?.online === false} />
      ) : noAnswerYet(status) ? (
        <span className="text-ink-2">{t`No answer yet`}</span>
      ) : (
        <MarkerList markers={status?.markers} />
      )}
    </li>
  );
}
