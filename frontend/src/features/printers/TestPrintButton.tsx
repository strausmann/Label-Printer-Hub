import { useLingui } from "@lingui/react/macro";
import { Link } from "@tanstack/react-router";
import { useState } from "react";
import { Button, Dialog, DialogTrigger, Popover } from "react-aria-components";
import { ApiError } from "../../api/client";
import { useSession } from "../../app/session";
import { PRIMARY_BUTTON } from "../../shell/SignIn";
import { SelectField } from "../settings/controls";
import { SECONDARY_BUTTON } from "../ui";
import { useTestPrint, type Printer, type PrinterStatus } from "./api";
import { isPagePrinter, unknownKind } from "./model";

/** Why the button cannot be pressed, or null. Tape printers are not refused on status: the server's preflight decides. */
function useBlockedReason(printer: Printer, status: PrinterStatus | undefined): string | null {
  const { t } = useLingui();
  if (!printer.enabled) return t`Printer is disabled`;
  if (printer.paused) return t`Printer is paused`;
  if (!isPagePrinter(printer, status)) return null;
  // A page printer has no preflight at submit time, so a status that is not a reading of it blocks.
  // No reading yet (still loading) is the same as none: pressing now would print blind.
  if (status === undefined || unknownKind(status) === "not_polled") return t`Printer status unknown`;
  if (status?.stale === true || status?.online === false) return t`Printer is not reachable`;
  return null;
}

/** The API's own words, or a plain sentence when the answer carried none (a bare `HTTP 500`). */
function useErrorText(error: unknown): string {
  const { t } = useLingui();
  if (error instanceof ApiError && !/^HTTP \d+$/.test(error.detail)) return error.detail;
  return t`The test print could not be started.`;
}

/**
 * Test print: one press on a tape printer, a tray choice in a small popover on a page printer.
 * Print scope and up; a read-only key does not see it. The answer stays next to the button
 * (a link to the job, or the API's reason) until the next press.
 */
export function TestPrintButton({ printer, status }: { printer: Printer; status: PrinterStatus | undefined }) {
  const { t } = useLingui();
  const scope = useSession().scope;
  const mutation = useTestPrint(printer.id);
  const reason = useBlockedReason(printer, status);
  const errorText = useErrorText(mutation.error);
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
          <Popover placement="bottom end" className="w-[min(20rem,calc(100vw-2rem))] rounded-r2 border border-line-strong bg-surface p-3 shadow-lg origin-(--trigger-anchor-point) data-[entering]:animate-[popin_140ms_cubic-bezier(0.23,1,0.32,1)]">
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
      <div aria-live="polite" className="max-w-xs text-small [overflow-wrap:anywhere]">
        {mutation.isSuccess && (
          <p role="status">
            {t`Test print sent.`}{" "}
            <Link to="/jobs/$jobId" params={{ jobId: mutation.data.job_id }} className="font-bold text-link underline underline-offset-2">
              {t`Open the job`}
            </Link>
          </p>
        )}
      </div>
      {mutation.isError && (
        <p role="alert" className="max-w-xs text-small text-bad [overflow-wrap:anywhere]">
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
