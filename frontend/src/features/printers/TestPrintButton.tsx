import { useLingui } from "@lingui/react/macro";
import { Link } from "@tanstack/react-router";
import { useState } from "react";
import { Button, Dialog, DialogTrigger, Popover } from "react-aria-components";
import { ApiError } from "../../api/client";
import { useSession } from "../../app/session";
import { SelectField } from "../settings/controls";
import { PRIMARY_BUTTON, SECONDARY_BUTTON } from "../ui";
import type { Printer, PrinterStatus, useTestPrint } from "./api";
import { isPagePrinter, printerStopReasons, unknownKind } from "./model";
import { useReasonWord } from "./reasons";

/** Why the button cannot be pressed, or null. Tape printers are not refused on status: the server's preflight decides. */
function useBlockedReason(printer: Printer, status: PrinterStatus | undefined): string | null {
  const { t } = useLingui();
  const word = useReasonWord();
  if (!printer.enabled) return t`Printer is disabled`;
  if (printer.paused) return t`Printer is paused`;
  if (!isPagePrinter(printer, status)) return null;
  // A page printer has no preflight at submit time, so a status that is not a reading of it blocks.
  // No reading yet (still loading) is the same as none: pressing now would print blind.
  if (status === undefined || unknownKind(status) === "not_polled") return t`Printer status unknown`;
  if (status?.stale === true || status?.online === false) return t`Printer is not reachable`;
  // A stopped printer (cover open, toner empty …) takes the job and holds it: name the reason instead.
  if (status?.printer_state === "stopped") {
    const reasons = printerStopReasons(status).map(word).join(" · ");
    return reasons ? t`Printer is stopped: ${reasons}` : t`Printer is stopped`;
  }
  return null;
}

/**
 * The app's own words for the refusals a person can act on (so a German UI does not show the hub's English);
 * the API's detail for a type it does not know; a plain sentence when the answer carried none (a bare `HTTP 500`).
 */
function useErrorText(error: unknown): string {
  const { t } = useLingui();
  if (error instanceof ApiError) {
    switch (error.code?.split("/").pop()) {
      case "printer-offline":
        return t`The printer is not reachable. Check that it is switched on and connected, then try again.`;
      case "no-tape-loaded":
        return t`No tape is loaded. Put in a tape and try again.`;
      case "media-unknown":
        return t`The printer does not report which paper is in the tray. Set the paper size on the printer or choose another tray.`;
      case "printer-disabled":
        return t`The printer is switched off in the hub. Switch it on in the printer settings.`;
      case "printer-paused":
        return t`The printer is paused. Resume it, then try again.`;
      case "printer-status-unknown":
        return t`The hub cannot read this printer's status, so it cannot tell whether it is ready. An admin can check its address in the printer settings, then try again.`;
    }
    if (!/^HTTP \d+$/.test(error.detail)) return error.detail;
  }
  return t`The test print could not be started.`;
}

export type TestPrintMutation = ReturnType<typeof useTestPrint>;

/**
 * Test print: one press on a tape printer, a tray choice in a small popover on a page printer.
 * Print scope and up; a read-only key does not see it. The answer (`TestPrintFeedback`) stays
 * under the header until the next press.
 */
export function TestPrintButton({ printer, status, mutation }: { printer: Printer; status: PrinterStatus | undefined; mutation: TestPrintMutation }) {
  const { t } = useLingui();
  const scope = useSession().scope;
  const reason = useBlockedReason(printer, status);
  const [open, setOpen] = useState(false);
  const page = isPagePrinter(printer, status);
  if (scope !== "print" && scope !== "admin") return null;
  const reasonId = `test-print-reason-${printer.id}`;
  const send = (tray: string | null) => mutation.mutate(tray, { onSettled: () => setOpen(false) });

  return (
    <div className="flex min-w-0 max-w-full flex-col items-start gap-1.5">
      {page ? (
        <DialogTrigger isOpen={open && reason === null} onOpenChange={setOpen}>
          <Button className={SECONDARY_BUTTON} isDisabled={reason !== null || mutation.isPending} aria-describedby={reason ? reasonId : undefined}>
            {t`Test print`}
          </Button>
          <Popover placement="bottom end" className="w-[min(20rem,calc(100vw-2rem))] rounded-r2 border border-line-strong bg-surface p-3 shadow-lg origin-(--trigger-anchor-point) data-[entering]:animate-[fadein_140ms_cubic-bezier(0.23,1,0.32,1)]">
            <Dialog aria-label={t`Test print`} className="flex flex-col gap-3 outline-none">
              <TrayChoice trays={status?.trays} pending={mutation.isPending} onPrint={send} />
            </Dialog>
          </Popover>
        </DialogTrigger>
      ) : (
        <Button className={SECONDARY_BUTTON} isDisabled={reason !== null || mutation.isPending} aria-describedby={reason ? reasonId : undefined} onPress={() => send(null)}>
          {t`Test print`}
        </Button>
      )}
      {reason && (
        <p id={reasonId} className="max-w-xs text-small text-ink-2 [overflow-wrap:anywhere]">
          {reason}
        </p>
      )}
    </div>
  );
}

/** The answer to the last press, in its own row under the header: a link to the job, or the hub's own words (wrapped, never cut). */
export function TestPrintFeedback({ mutation }: { mutation: TestPrintMutation }) {
  const { t } = useLingui();
  const errorText = useErrorText(mutation.error);
  // Nothing at rest: an empty row would still take a gap in the page's column.
  if (!mutation.isSuccess && !mutation.isError) return null;
  return (
    <div className="text-small [overflow-wrap:anywhere]">
      {mutation.isSuccess && (
        <p role="status">
          {t`Test print sent.`}{" "}
          <Link to="/jobs/$jobId" params={{ jobId: mutation.data.job_id }} className="font-bold text-link underline underline-offset-2">
            {t`Open the job`}
          </Link>
        </p>
      )}
      {mutation.isError && (
        <p role="alert" className="max-w-prose text-bad">
          {errorText}
        </p>
      )}
    </div>
  );
}

/** The tray to print on: enabled trays only, the default preselected. */
function TrayChoice({ trays, pending, onPrint }: { trays: PrinterStatus["trays"]; pending: boolean; onPrint: (tray: string | null) => void }) {
  const { t } = useLingui();
  const enabled = (trays ?? []).filter((tray) => tray.enabled);
  const [picked, setPicked] = useState<string | null>(null);
  const chosen = enabled.find((tray) => tray.key === picked) ?? enabled.find((tray) => tray.is_default) ?? enabled[0];
  if (!chosen) return <p className="text-small text-ink-2">{t`The printer reports no trays.`}</p>;
  return (
    <>
      <SelectField label={t`Tray`} value={chosen.key} options={enabled.map((tray) => ({ id: tray.key, label: tray.label }))} onChange={setPicked} />
      <Button className={PRIMARY_BUTTON} isDisabled={pending} onPress={() => onPrint(chosen.key)}>
        {t`Print test page`}
      </Button>
    </>
  );
}
