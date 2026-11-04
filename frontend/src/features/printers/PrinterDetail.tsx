import { useLingui } from "@lingui/react/macro";
import { getRouteApi, Link } from "@tanstack/react-router";
import { useState } from "react";
import { Button } from "react-aria-components";
import { ApiError } from "../../api/client";
import { useFeature } from "../../app/session";
import { StatusBadge } from "../../shell/StatusBadge";
import { PANEL, SECONDARY_BUTTON, SECTION_HEADING } from "../ui";
import { useCancelJob, useClearQueue, usePrinter, usePrinterStatus, useQueue, type Printer, type QueueJob } from "./api";
import { describePrinter, useJobStateBadge, useKindLabel } from "./model";
import { PauseResumeButton } from "./PauseResumeButton";
import { TapeSwatch } from "./TapeSwatch";

const route = getRouteApi("/printers/$printerId");

export function PrinterPage() {
  const { t } = useLingui();
  const { printerId } = route.useParams();
  const printer = usePrinter(printerId);
  if (printer.isPending) return <p role="status" className="text-ink-2">{t`Loading…`}</p>;
  if (printer.isError) {
    const missing = printer.error instanceof ApiError && printer.error.status === 404;
    return (
      <div className="flex flex-col gap-3">
        <p role="alert">{missing ? t`This printer does not exist.` : t`The printer could not be loaded.`}</p>
        <Link to="/printers" className="text-link underline underline-offset-2">
          {t`Back to the printers`}
        </Link>
      </div>
    );
  }
  return <PrinterDetail printer={printer.data} />;
}

function PrinterDetail({ printer }: { printer: Printer }) {
  const { t } = useLingui();
  const kinds = useKindLabel();
  const status = usePrinterStatus(printer.id);
  const queue = useQueue(printer.id);
  const calibration = useFeature("calibration");
  const printing = (queue.data ?? []).some((j) => j.state === "printing");
  const view = describePrinter(printer, status.data, printing);
  const age = status.data?.last_probe_age_s;

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex flex-col gap-2">
          <h1 className="text-title font-bold">{printer.name}</h1>
          <StatusBadge state={view.badge} label={kinds[view.kind]} />
          {view.detail && <p className="text-small text-ink-2">{view.detail}</p>}
        </div>
        <PauseResumeButton printer={printer} />
      </header>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="flex flex-col gap-4">
          <section aria-labelledby="material-h" className={PANEL}>
            <h2 id="material-h" className={SECTION_HEADING}>{t`Material`}</h2>
            <p className="mt-3">
              <TapeSwatch tapeLoaded={status.data?.tape_loaded} probed={status.data?.captured_at != null} />
            </p>
            {typeof age === "number" && (
              <p className="mt-2 text-small text-ink-2">{t`Last status ${age} s ago`}</p>
            )}
          </section>
          <QueueSection printer={printer} jobs={queue.data} loading={queue.isPending} failed={queue.isError} />
        </div>

        <div className="flex flex-col gap-4">
          <section aria-labelledby="connection-h" className={PANEL}>
            <h2 id="connection-h" className={SECTION_HEADING}>{t`Connection`}</h2>
            <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-2">
              <Row label={t`Model`} value={printer.model} />
              <Row label={t`Backend`} value={printer.backend} mono />
              <Row label={t`Host`} value={textOf(printer.connection.host)} mono />
              <Row label={t`Port`} value={textOf(printer.connection.port)} mono />
            </dl>
          </section>
          {calibration && (
            <section aria-labelledby="calibration-h" className={PANEL}>
              <h2 id="calibration-h" className={SECTION_HEADING}>{t`Calibration`}</h2>
              <p className="mt-3 text-ink-2">{t`Calibration for this printer will appear here.`}</p>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}

/** Shown as stored: no trimming, no case change. */
const textOf = (value: unknown): string | null =>
  typeof value === "string" || typeof value === "number" ? String(value) : null;

function Row({ label, value, mono = false }: { label: string; value: string | null; mono?: boolean }) {
  return (
    <>
      <dt className="text-ink-2">{label}</dt>
      <dd className={`min-w-0 break-words ${mono ? "code" : ""}`}>{value ?? "—"}</dd>
    </>
  );
}

function QueueSection({
  printer,
  jobs,
  loading,
  failed,
}: {
  printer: Printer;
  jobs: QueueJob[] | undefined;
  loading: boolean;
  failed: boolean;
}) {
  const { t } = useLingui();
  const stateOf = useJobStateBadge();
  const cancel = useCancelJob(printer.id);
  const clear = useClearQueue(printer.id);
  const [confirming, setConfirming] = useState(false);
  const queued = (jobs ?? []).filter((j) => j.state === "queued").length;

  return (
    <section aria-labelledby="queue-h" className={PANEL}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id="queue-h" className={SECTION_HEADING}>{t`Queue`}</h2>
        {queued > 0 &&
          (confirming ? (
            <span className="flex flex-wrap items-center gap-2">
              <Button
                className={SECONDARY_BUTTON}
                isDisabled={clear.isPending}
                onPress={() => clear.mutate(undefined, { onSettled: () => setConfirming(false) })}
              >
                {t`Cancel ${queued} queued`}
              </Button>
              <Button className={SECONDARY_BUTTON} onPress={() => setConfirming(false)}>
                {t`Keep them`}
              </Button>
            </span>
          ) : (
            <Button className={SECONDARY_BUTTON} onPress={() => setConfirming(true)}>
              {t`Clear queue`}
            </Button>
          ))}
      </div>
      {loading && <p role="status" className="mt-3 text-ink-2">{t`Loading…`}</p>}
      {failed && <p role="alert" className="mt-3 text-bad">{t`The queue could not be loaded.`}</p>}
      {jobs && jobs.length === 0 && <p className="mt-3 text-ink-2">{t`Nothing is waiting.`}</p>}
      {jobs && jobs.length > 0 && (
        <ul className="mt-3 flex flex-col gap-2">
          {jobs.map((job) => {
            const label = job.template_key ?? t`Label`;
            const state = stateOf(job.state);
            return (
              <li key={job.id} className="flex flex-wrap items-center justify-between gap-3 rounded-r2 bg-sunken px-3 py-2">
                <span className="flex min-w-0 flex-col">
                  <Link to="/jobs/$jobId" params={{ jobId: job.id }} className="font-bold text-link underline underline-offset-2">
                    {label}
                  </Link>
                  <span className="text-small text-ink-2">{time(job.created_at)}</span>
                </span>
                <span className="flex items-center gap-3">
                  <StatusBadge state={state.badge} label={state.label} />
                  {/* Only a waiting job can be cancelled: a printing one is already on the wire. */}
                  {job.state === "queued" && (
                    <Button
                      className={SECONDARY_BUTTON}
                      aria-label={t`Cancel ${label}`}
                      isDisabled={cancel.isPending}
                      onPress={() => cancel.mutate(job.id)}
                    >
                      {t`Cancel`}
                    </Button>
                  )}
                </span>
              </li>
            );
          })}
        </ul>
      )}
      {(cancel.isError || clear.isError) && (
        <p role="alert" className="mt-3 text-small text-bad">{t`The job could not be cancelled.`}</p>
      )}
    </section>
  );
}

const time = (iso: string) => {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleString([], { dateStyle: "short", timeStyle: "short" });
};
