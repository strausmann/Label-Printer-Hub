// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useLingui } from "@lingui/react/macro";
import { useEffect, useRef, useState } from "react";
import { Button } from "react-aria-components";
import { useCapabilities } from "../../calibration/api";
import { useJob } from "../../jobs/api";
import { useJobErrorText } from "../../jobs/jobErrorText";
import { claimJob, errorCodeFromMessage, useJobLive, watchPrint } from "../../jobs/printWatch";
import { usePrinters } from "../../printers/api";
import { HINT, SelectField } from "../../settings/controls";
import { PRIMARY_BUTTON, SECONDARY_BUTTON } from "../../ui";
import { useConfirmBackSide, useCreateSheet, usePrintBackSide, type SheetCreate } from "../api";
import { useSheetErrorText } from "../errors";
import { LinerPreview } from "./LinerPreview";
import { LoadingPicture } from "./LoadingPicture";
import { backSideInstruction } from "./loading";
import type { StripMm } from "./strip";
import { TrayLoadingTest } from "./TrayLoadingTest";

/** What is activated: a sheet still to create (the code is a hint until then), or one that exists. */
export type BackSideTarget =
  | { kind: "new"; body: Omit<SheetCreate, "id_placement" | "printer" | "tray" | "id_cell"> }
  | { kind: "existing"; code: string };

type Step = "turn" | "print" | "confirm";

const LINK_BUTTON =
  "inline-flex min-h-11 items-center text-link font-bold underline underline-offset-2 data-[focus-visible]:outline-3 data-[focus-visible]:outline-offset-2 data-[focus-visible]:outline-link";

function Stepper({ step }: { step: Step }) {
  const { t } = useLingui();
  const steps: { id: Step; label: string }[] = [
    { id: "turn", label: t`Turn over` },
    { id: "print", label: t`Print` },
    { id: "confirm", label: t`Confirm` },
  ];
  const at = steps.findIndex((s) => s.id === step);
  return (
    <ol aria-label={t`Steps`} className="m-0 flex list-none flex-wrap items-center gap-2 p-0">
      {steps.map((s, i) => {
        const reached = i <= at;
        const current = i === at;
        return (
          <li key={s.id} aria-current={current ? "step" : undefined} className="flex items-center gap-2">
            <span
              aria-hidden="true"
              className={`flex size-7 shrink-0 items-center justify-center rounded-full text-small font-bold ${
                reached ? "bg-accent text-accent-ink" : "border-2 border-line-strong text-ink-2"
              }`}
            >
              {i + 1}
            </span>
            {/* On a phone only the current step carries its word; the numbers keep the place. */}
            <span className={`text-small font-bold ${current ? "text-ink" : "hidden text-ink-2 sm:inline"}`}>{s.label}</span>
            {i < steps.length - 1 ? <span aria-hidden="true" className="h-px w-5 bg-line-strong" /> : null}
          </li>
        );
      })}
    </ol>
  );
}

/**
 * Activating a sheet whose code goes on the back of the liner (#350, mockup 350-2): turn it over, print the
 * code strip, confirm that it came out clean. The job alone never marks the code as printed (R-350-6);
 * closing before "Yes, it is printed" leaves the sheet unconfirmed, and the sheet page offers this again.
 */
export function ActivateBackSide({
  target,
  codeLabel,
  typeLabel,
  page,
  strips,
  initialPrinterId,
  initialTray,
  onUseCell,
  onClose,
}: {
  target: BackSideTarget;
  /** The sheet's code, or the code it will probably get. */
  codeLabel: string;
  typeLabel: string;
  page: { w: number; h: number };
  strips: readonly StripMm[];
  initialPrinterId?: string;
  initialTray?: string | null;
  /** "Use a reserved cell instead": back to the dialog with the reserved cell chosen. */
  onUseCell?: () => void;
  onClose: () => void;
}) {
  const { t } = useLingui();
  const errorText = useSheetErrorText();
  const jobErrorText = useJobErrorText();
  const printers = usePrinters();
  const pagePrinters = (printers.data ?? []).filter((p) => p.backend === "ipp" && p.enabled);
  const [printerId, setPrinterId] = useState(initialPrinterId ?? "");
  const effectivePrinter = printerId || pagePrinters[0]?.id || "";
  const caps = useCapabilities(effectivePrinter);
  const trays = (caps.data?.trays ?? []).filter((x) => x.enabled);
  const [trayChoice, setTrayChoice] = useState<string | null>(initialTray ?? null);
  const tray = trays.find((x) => x.key === trayChoice) ?? trays.find((x) => x.is_default) ?? trays[0];
  const loading = tray?.loading ?? null;

  const [requested, setStep] = useState<Step>("turn");
  const [code, setCode] = useState<string | null>(target.kind === "existing" ? target.code : null);
  const [jobId, setJobId] = useState<string | null>(null);
  const create = useCreateSheet();
  const again = usePrintBackSide();
  const confirm = useConfirmBackSide();
  const live = useJobLive(jobId);
  const job = useJob(jobId ?? "", jobId !== null);
  const phase = live?.phase ?? (job.data?.state === "done" ? "done" : job.data?.state === "failed" ? "failed" : "queued");

  useEffect(() => (jobId ? claimJob(jobId) : undefined), [jobId]);
  // Each step starts at its top: the dialog may still be scrolled to where the form's button was (phones).
  const top = useRef<HTMLDivElement>(null);
  const stepKey = requested === "print" && phase === "done" ? "confirm" : requested;
  useEffect(() => top.current?.scrollIntoView?.({ block: "start" }), [stepKey]);
  // The page came out: the person checks it. "Print again" queues a new job, which is not done yet.
  const step: Step = requested === "print" && phase === "done" ? "confirm" : requested;

  const started = (newJob: string) => {
    watchPrint({ kind: "sheet", printerId: effectivePrinter, jobIds: [newJob], claimPending: true });
    setJobId(newJob);
    setStep("print");
  };

  function printCode() {
    if (!tray || !effectivePrinter) return;
    if (code !== null) {
      again.mutate({ code, body: { printer: effectivePrinter, tray: tray.key } }, { onSuccess: (q) => started(q.job_id) });
      return;
    }
    if (target.kind !== "new") return;
    create.mutate(
      { ...target.body, id_placement: "back_side", printer: effectivePrinter, tray: tray.key },
      {
        onSuccess: (created) => {
          setCode(created.code);
          if (created.job_id) started(created.job_id);
        },
      },
    );
  }

  const shownCode = code ?? codeLabel;
  const trayLabel = tray?.label ?? "";
  const linerUp = loading ? backSideInstruction(loading).linerSide === "up" : true;
  const busy = create.isPending || again.isPending;
  const failedCode = live?.errorCode ?? errorCodeFromMessage(job.data?.error);
  const requestError = create.error ?? again.error;

  return (
    <div ref={top} className="flex min-w-0 scroll-mt-4 flex-col gap-5" data-testid="activate-back-side">
      <header className="flex flex-col gap-1">
        <p className="text-small text-ink-2 [overflow-wrap:anywhere]">
          {typeLabel} · {t`sheet code`} <span className="font-mono whitespace-nowrap">{shownCode}</span>
        </p>
        <Stepper step={step} />
      </header>

      {step === "turn" ? (
        <div className="grid min-w-0 gap-5 md:grid-cols-[minmax(0,17rem)_minmax(0,1fr)]">
          <LoadingPicture loading={loading} />
          <div className="flex min-w-0 flex-col gap-4">
            <h3 className="text-section font-bold">{t`Put the sheet in the other way round`}</h3>
            <ol className="m-0 flex list-none flex-col gap-4 p-0">
              <li className="flex gap-3">
                <span aria-hidden="true" className="flex size-7 shrink-0 items-center justify-center rounded-full bg-ink font-bold text-surface">1</span>
                <span className="flex min-w-0 flex-col">
                  <span className="font-bold">{t`Turn the sheet over along the long edge`}</span>
                  <span className="text-ink-2">{t`Like turning a page: the top edge stays on top. You now see the liner.`}</span>
                </span>
              </li>
              <li className="flex gap-3">
                <span aria-hidden="true" className="flex size-7 shrink-0 items-center justify-center rounded-full bg-ink font-bold text-surface">2</span>
                <span className="flex min-w-0 flex-col">
                  <span className="font-bold [overflow-wrap:anywhere]">
                    {!loading
                      ? t`Load it into ${trayLabel}`
                      : linerUp
                        ? t`Load it into ${trayLabel}, liner side up`
                        : t`Load it into ${trayLabel}, liner side down`}
                  </span>
                  <span className="text-ink-2">{t`Top edge goes in first. A wrongly loaded sheet still works, the QR code reads in any orientation.`}</span>
                </span>
              </li>
            </ol>
            <div className="grid gap-3 sm:grid-cols-2">
              <SelectField
                label={t`Printer`}
                value={effectivePrinter}
                options={pagePrinters.map((p) => ({ id: p.id, label: p.name }))}
                onChange={(id) => {
                  setPrinterId(id);
                  setTrayChoice(null);
                }}
              />
              {trays.length > 0 ? (
                <SelectField label={t`Tray`} value={tray?.key ?? ""} options={trays.map((x) => ({ id: x.key, label: x.label }))} onChange={setTrayChoice} />
              ) : null}
            </div>
            {loading ? <p className={HINT}>{t`Set for this tray in the printer settings.`}</p> : null}
            {pagePrinters.length === 0 && printers.isSuccess ? <p className={HINT}>{t`No page printer is set up.`}</p> : null}
            {tray && !loading ? <TrayLoadingTest printerId={effectivePrinter} trayKey={tray.key} trayLabel={tray.label} /> : null}
          </div>
        </div>
      ) : null}

      {step === "print" ? (
        <div role="status" className="flex flex-col gap-3">
          {phase === "failed" ? (
            <>
              <p className="text-section font-bold text-bad">{t`The sheet code could not be printed.`}</p>
              <p className="[overflow-wrap:anywhere]">{jobErrorText(failedCode)}</p>
            </>
          ) : (
            <p className="text-section font-bold">{phase === "printing" ? t`Printing the sheet code…` : t`The sheet code is in the print queue.`}</p>
          )}
        </div>
      ) : null}

      {step === "confirm" ? (
        <div className="flex flex-col items-center gap-3 text-center">
          <h3 className="text-section font-bold">{t`Did it print?`}</h3>
          <p className="max-w-prose text-ink-2">{t`Check that the toner is dry and the QR code is not smeared. If it is, print again on the same sheet.`}</p>
          <div className="rounded-r3 bg-sunken p-3">
            <LinerPreview page={page} strips={strips} code={shownCode} />
          </div>
          <p className="text-small text-ink-2">{t`Back of the liner, as printed`}</p>
        </div>
      ) : null}

      {requestError ? <p role="alert" className="font-bold text-bad">{errorText(requestError, t`The sheet code could not be printed.`)}</p> : null}
      {confirm.isError ? <p role="alert" className="font-bold text-bad">{errorText(confirm.error)}</p> : null}

      {/* The main action stays in reach while the steps scroll inside the dialog (phone: sticky footer). */}
      <div className="sticky -bottom-4 -mx-4 -mb-4 flex flex-col gap-2 border-t border-line bg-surface px-4 pt-3 pb-[calc(1rem+env(safe-area-inset-bottom,0px))] sm:-bottom-6 sm:-mx-6 sm:-mb-6 sm:flex-row sm:flex-wrap sm:items-center sm:px-6 sm:pb-6">
        {step === "turn" ? (
          <>
            <Button onPress={printCode} isDisabled={!tray || !loading || busy} className={PRIMARY_BUTTON}>
              {t`Print sheet code`}
            </Button>
            {onUseCell ? (
              <Button onPress={onUseCell} className={LINK_BUTTON}>
                {t`Use a reserved cell instead`}
              </Button>
            ) : null}
            <Button onPress={onClose} className={`${SECONDARY_BUTTON} sm:ml-auto`}>
              {t`Cancel`}
            </Button>
          </>
        ) : null}
        {step === "print" ? (
          <>
            {phase === "failed" ? (
              <Button onPress={printCode} isDisabled={busy} className={PRIMARY_BUTTON}>
                {t`Print again`}
              </Button>
            ) : null}
            <Button onPress={onClose} className={SECONDARY_BUTTON}>
              {t`Close`}
            </Button>
          </>
        ) : null}
        {step === "confirm" && code ? (
          <>
            <Button onPress={() => confirm.mutate(code, { onSuccess: onClose })} isDisabled={confirm.isPending} className={PRIMARY_BUTTON}>
              {t`Yes, it is printed`}
            </Button>
            <Button onPress={printCode} isDisabled={busy} className={SECONDARY_BUTTON}>
              {t`Print again`}
            </Button>
          </>
        ) : null}
      </div>
    </div>
  );
}
