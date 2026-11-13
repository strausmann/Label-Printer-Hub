import { plural } from "@lingui/core/macro";
import { useLingui } from "@lingui/react/macro";
import { getRouteApi, Link } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { Button } from "react-aria-components";
import { ApiError } from "../../api/client";
import { useFeature, useSession } from "../../app/session";
import { StatusBadge } from "../../shell/StatusBadge";
import { PANEL, SECONDARY_BUTTON, SECTION_HEADING } from "../ui";
import { TEST_LABEL_KEY } from "../jobs/model";
import { useCalibration, type CalibrationRead } from "../calibration/api";
import { useCancelJob, useClearQueue, usePrinter, usePrinterStatus, useQueue, useTestPrint, type Printer, type PrinterStatus, type QueueJob } from "./api";
import { IdentityMismatchBanner, SettledNotice, useIdentityKindLabel } from "./IdentityMismatchBanner";
import { PauseReason } from "./PauseReason";
import { formatAge } from "./age";
import { describePrinter, isPagePrinter, staleAgeSeconds, statusIsUnknown, tapeWidthOf, useJobStateBadge, useKindLabel } from "./model";
import { MarkerList, noAnswerYet, NotMonitoredHint, ReasonLine } from "./PageStatus";
import { TestPrintButton, TestPrintFeedback } from "./TestPrintButton";
import { PauseResumeButton } from "./PauseResumeButton";
import { RollColourEdit, RollColourPrompt } from "./RollColourPrompt";
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
  // Keyed by the printer: a switch to another printer starts with a clean page (no leftover notices or open panels).
  return <PrinterDetail key={printer.data.id} printer={printer.data} />;
}

function PrinterDetail({ printer }: { printer: Printer }) {
  const { t, i18n } = useLingui();
  const kinds = useKindLabel();
  const status = usePrinterStatus(printer.id);
  const queue = useQueue(printer.id);
  const calibration = useFeature("calibration");
  const printing = (queue.data ?? []).some((j) => j.state === "printing");
  const view = describePrinter(printer, status.data, printing);
  const page = isPagePrinter(printer, status.data);
  // The union is wider than what the server sends: an IPP printer's address is left out for keys below admin.
  const connection: Record<string, unknown> = printer.connection;
  const unknown = statusIsUnknown(status.data);
  const unanswered = page && !unknown && noAnswerYet(status.data);
  // Same rule as the card: only a status that is not a reading of the printer now has an age worth naming.
  const age = staleAgeSeconds(status.data);
  const ageWord = typeof age === "number" ? formatAge(age, i18n.locale) : "";
  const ahead = status.data?.jobs_ahead ?? 0;
  // Only a key that may write is asked; a status nobody refreshes says nothing about the roll.
  const session = useSession();
  const admin = session.scope === "admin";
  const identityKind = useIdentityKindLabel();
  const [settledNotice, setSettledNotice] = useState(false);
  // A swap that comes back is a new question: the "settled already" note of the last one must not answer it.
  const mismatch = status.data?.identity_mismatch === true;
  const [wasMismatch, setWasMismatch] = useState(mismatch);
  if (mismatch !== wasMismatch) {
    setWasMismatch(mismatch);
    if (mismatch) setSettledNotice(false);
  }
  const canAskColour = (session.scope === "print" || session.scope === "admin") && !page && !unknown;
  const testPrint = useTestPrint(printer.id);
  const colourTrigger = useRef<HTMLButtonElement | null>(null);
  // Answering the roll question removes the prompt, and the focus with it. Once the page has dropped the
  // prompt, focus goes to the control that edits the colour, or to the material heading when there is none
  // (a roll without a known width has no such control).
  const materialHeading = useRef<HTMLHeadingElement | null>(null);
  const refocusAfterPrompt = useRef(false);
  const promptShown = canAskColour && status.data?.roll_prompt === true;
  useEffect(() => {
    if (promptShown || !refocusAfterPrompt.current) return;
    refocusAfterPrompt.current = false;
    (colourTrigger.current ?? materialHeading.current)?.focus();
  }, [promptShown]);

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex flex-col gap-2">
          <h1 className="text-title font-bold">{printer.name}</h1>
          <StatusBadge state={view.badge} label={kinds[view.kind]} />
          {view.detail && <p className="text-small text-ink-2">{view.detail}</p>}
          {view.kind === "not_polled" && <NotMonitoredHint printer={printer} page={page} linked />}
          {view.kind === "paused" && <PauseReason pause={printer.pause} />}
          <ReasonLine reasons={view.reasons} />
          {page && ahead > 0 && (
            <p className="text-small text-ink-2">
              {plural(ahead, { one: "# job from another computer ahead", other: "# jobs from other computers ahead" })}
            </p>
          )}
        </div>
        <div className="flex min-w-0 max-w-full flex-wrap items-start gap-2">
          <TestPrintButton printer={printer} status={status.data} mutation={testPrint} />
          <PauseResumeButton printer={printer} />
        </div>
      </header>
      <TestPrintFeedback mutation={testPrint} />
      {mismatch && <IdentityMismatchBanner printer={printer} onSettled={() => setSettledNotice(true)} />}
      {settledNotice && !mismatch && <SettledNotice />}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="flex min-w-0 flex-col gap-4">
          {page ? (
            <>
              <section aria-labelledby="supplies-h" className={PANEL}>
                <h2 id="supplies-h" className={SECTION_HEADING}>{t`Supplies`}</h2>
                <div className="mt-3">
                  {unknown ? (
                    <span className="text-ink-2">{t`Supplies not known`}</span>
                  ) : unanswered ? (
                    <span className="text-ink-2">{t`No answer yet`}</span>
                  ) : (
                    <MarkerList markers={status.data?.markers} />
                  )}
                </div>
                {typeof age === "number" && (
                  <p className="mt-2 text-small text-ink-2">{t`Last status ${ageWord}`}</p>
                )}
              </section>
              <TraysSection trays={status.data?.trays} unanswered={unanswered} />
            </>
          ) : (
            <>
              {canAskColour && (
                <RollColourPrompt
                  printer={printer}
                  status={status.data}
                  onDone={() => {
                    refocusAfterPrompt.current = true;
                  }}
                />
              )}
              <section aria-labelledby="material-h" className={PANEL}>
                <h2 id="material-h" ref={materialHeading} tabIndex={-1} className={SECTION_HEADING}>{t`Material`}</h2>
                <p className="mt-3">
                  {unknown ? (
                    <span className="text-ink-2">{t`Tape not known`}</span>
                  ) : (
                    <TapeSwatch widthMm={tapeWidthOf(status.data)} colour={status.data?.tape_colour} probed={status.data?.captured_at != null} offline={status.data?.online === false} />
                  )}
                </p>
                {canAskColour && tapeWidthOf(status.data) !== null && (
                  <div className="mt-3">
                    <RollColourEdit printer={printer} status={status.data} triggerRef={colourTrigger} />
                  </div>
                )}
                {typeof age === "number" && (
                  <p className="mt-2 text-small text-ink-2">{t`Last status ${ageWord}`}</p>
                )}
              </section>
            </>
          )}
          <QueueSection printer={printer} jobs={queue.data} loading={queue.isPending} failed={queue.isError} />
        </div>

        <div className="flex min-w-0 flex-col gap-4">
          <section aria-labelledby="connection-h" className={PANEL}>
            <h2 id="connection-h" className={SECTION_HEADING}>{t`Connection`}</h2>
            <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-2">
              <Row label={t`Model`} value={printer.model} />
              <Row label={t`Backend`} value={printer.backend} mono />
              {printer.backend === "ipp" ? (
                <>
                  {/* Only an admin gets the address; every other key gets the certificate setting alone. */}
                  {typeof connection.uri === "string" && <Row label={t`Address`} value={connection.uri} mono />}
                  {typeof connection.tls_verify === "boolean" && (
                    <Row label={t`Certificate check`} value={connection.tls_verify ? t`on` : t`off`} />
                  )}
                </>
              ) : (
                <>
                  <Row label={t`Host`} value={textOf(connection.host)} mono />
                  <Row label={t`Port`} value={textOf(connection.port)} mono />
                </>
              )}
              {admin && printer.hardware_id && <Row label={identityKind(printer.hardware_id_kind)} value={printer.hardware_id} mono />}
            </dl>
            {/* Only an admin is told: the identity is hidden from every other key, so its absence says nothing to them. */}
            {admin && !printer.hardware_id && (
              <p className="mt-3 text-small text-ink-2">{t`No hardware identity — device swaps are not detected`}</p>
            )}
          </section>
          {calibration && (
            <section aria-labelledby="calibration-h" className={PANEL}>
              <h2 id="calibration-h" className={SECTION_HEADING}>{t`Calibration`}</h2>
              {page ? (
                <PageCalibration printer={printer} trays={status.data?.trays} held={mismatch} />
              ) : (
                <p className="mt-3 text-ink-2">{t`Calibration for this printer will appear here.`}</p>
              )}
            </section>
          )}
        </div>
      </div>
    </div>
  );
}

type Tray = NonNullable<PrinterStatus["trays"]>[number];

/** The trays the printer reports, with what is loaded and the hint where to put paper. Long keys and hints wrap. */
function TraysSection({ trays, unanswered }: { trays: PrinterStatus["trays"]; unanswered: boolean }) {
  const { t } = useLingui();
  const shown = (trays ?? []).filter((tray) => tray.enabled);
  return (
    <section aria-labelledby="trays-h" className={PANEL}>
      <h2 id="trays-h" className={SECTION_HEADING}>{t`Trays`}</h2>
      {shown.length === 0 ? (
        <p className="mt-3 text-ink-2">{unanswered ? t`Trays are listed once the printer has answered.` : t`The printer reports no trays.`}</p>
      ) : (
        <ul className="mt-3 flex flex-col gap-2">
          {shown.map((tray) => (
            <li key={tray.key} className="flex min-w-0 flex-col gap-0.5 rounded-r2 bg-sunken px-3 py-2">
              <span className="font-bold [overflow-wrap:anywhere]">
                {tray.label}
                {tray.is_default && <span className="ml-2 text-small font-normal text-ink-2">{t`default`}</span>}
              </span>
              {tray.media && <span className="text-small [overflow-wrap:anywhere]">{tray.media}</span>}
              {tray.load_hint && <span className="text-small text-ink-2 [overflow-wrap:anywhere]">{tray.load_hint}</span>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

const rounded = (value: number) => Math.round(value * 100) / 100;

/** One line per tray: calibrated or not, and the way to the calibration page (admin only). */
function PageCalibration({ printer, trays, held }: { printer: Printer; trays: Tray[] | null | undefined; held: boolean }) {
  const { t } = useLingui();
  const admin = useSession().scope === "admin";
  const calibration = useCalibration(printer.id);
  if (calibration.isPending) return <p role="status" className="mt-3 text-ink-2">{t`Loading…`}</p>;
  if (calibration.isError) return <p role="alert" className="mt-3 text-bad">{t`The calibration could not be loaded.`}</p>;
  if (calibration.data.length === 0) return <p className="mt-3 text-ink-2">{t`No tray to calibrate.`}</p>;
  const heldId = `calibration-held-${printer.id}`;
  const label = (row: CalibrationRead) => trays?.find((tray) => tray.key === row.tray)?.label ?? row.tray;
  return (
    <>
      {/* The calibration page is held for everyone while another device answers at the address; say why the buttons are off. */}
      {held && (
        <p id={heldId} className="mt-3 text-small text-ink-2">
          {t`Calibration is held until an admin settles the device swap.`}
        </p>
      )}
      <ul className="mt-3 flex flex-col gap-2">
        {calibration.data.map((row) => {
          const done = [row.offset_x_mm, row.offset_y_mm, row.scale_x, row.scale_y, row.rotation_deg].some((v) => v != null);
          const name = label(row);
          const dx = row.offset_x_mm == null ? null : rounded(row.offset_x_mm);
          const dy = row.offset_y_mm == null ? null : rounded(row.offset_y_mm);
          return (
            <li key={row.tray} className="flex flex-wrap items-center justify-between gap-3 rounded-r2 bg-sunken px-3 py-2">
              <span className="flex min-w-0 flex-col">
                <span className="font-bold [overflow-wrap:anywhere]">{name}</span>
                <span className="text-small text-ink-2">
                  {done ? t`Calibrated` : t`Not calibrated`}
                  {dx !== null && dy !== null && <> · {t`Offset ${dx} / ${dy} mm`}</>}
                </span>
              </span>
              {admin && held && (
                <Button isDisabled aria-label={t`Calibrate ${name}`} aria-describedby={heldId} className={SECONDARY_BUTTON}>
                  {t`Calibrate`}
                </Button>
              )}
              {admin && !held && (
                <Link
                  to="/calibration"
                  search={{ printer: printer.id, tray: row.tray }}
                  aria-label={t`Calibrate ${name}`}
                  className="press inline-flex h-11 items-center justify-center rounded-r2 border border-line-strong bg-surface px-4 text-small font-bold text-ink transition-colors duration-150 hover:bg-sunken focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-link"
                >
                  {t`Calibrate`}
                </Link>
              )}
            </li>
          );
        })}
      </ul>
    </>
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
            const label = job.template_key === TEST_LABEL_KEY ? t`Test label` : (job.template_key ?? t`Label`);
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
