import { useLingui } from "@lingui/react/macro";
import { Link } from "@tanstack/react-router";
import { StatusBadge } from "../../shell/StatusBadge";
import type { Printer, PrinterStatus } from "./api";
import { PauseReason } from "./PauseReason";
import { formatAge } from "./age";
import { describePrinter, isPagePrinter, statusIsUnknown, tapeWidthOf, useKindLabel } from "./model";
import { MarkerList, noAnswerYet, ReasonLine } from "./PageStatus";
import { TapeSwatch } from "./TapeSwatch";

/** One printer: name, state (shape + word), loaded tape, or supplies for a page printer. The whole card opens the detail page. */
export function PrinterCard({
  printer,
  status,
  printing,
}: {
  printer: Printer;
  status: PrinterStatus | undefined;
  printing: boolean;
}) {
  const { t, i18n } = useLingui();
  const kinds = useKindLabel();
  const view = describePrinter(printer, status, printing);
  const page = isPagePrinter(printer, status);
  const unknown = statusIsUnknown(status);
  const age = view.kind === "stale" ? status?.last_probe_age_s : null;
  const ageWord = typeof age === "number" ? formatAge(age, i18n.locale) : "";
  return (
    <Link
      to="/printers/$printerId"
      params={{ printerId: printer.id }}
      className="press flex h-full min-w-0 flex-col gap-3 rounded-r3 border border-line bg-surface p-4 transition-colors duration-150 hover:bg-sunken focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-link"
    >
      <span className="flex flex-col">
        <span className="text-body font-bold [overflow-wrap:anywhere]">{printer.name}</span>
        <span className="text-small text-ink-2 [overflow-wrap:anywhere]">{printer.model}</span>
      </span>
      <StatusBadge state={view.badge} label={kinds[view.kind]} />
      {status?.identity_mismatch === true && <StatusBadge state="warn" label={t`Different device`} />}
      {view.detail && <span className="text-small text-ink-2">{view.detail}</span>}
      {view.kind === "paused" && <PauseReason pause={printer.pause} />}
      {typeof age === "number" && (
        <span className="text-small text-ink-2 [overflow-wrap:anywhere]">{t`Last status ${ageWord}`}</span>
      )}
      <ReasonLine reasons={view.reasons} />
      <span className="mt-auto min-w-0 text-small">
        {unknown ? (
          <span className="text-ink-2">{page ? t`Supplies not known` : t`Tape not known`}</span>
        ) : !page ? (
          <TapeSwatch widthMm={tapeWidthOf(status)} colour={status?.tape_colour} probed={status?.captured_at != null} offline={status?.online === false} />
        ) : noAnswerYet(status) ? (
          <span className="text-ink-2">{t`No answer yet`}</span>
        ) : (
          <MarkerList markers={status?.markers} />
        )}
      </span>
    </Link>
  );
}
