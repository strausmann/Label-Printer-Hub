import { useLingui } from "@lingui/react/macro";
import { Link } from "@tanstack/react-router";
import { useSession } from "../../app/session";
import type { PrinterStatus } from "./api";
import { MarkerSwatch } from "./MarkerSwatch";
import { useReasonWord } from "./reasons";

/**
 * A page printer that never answered (#206): the hub stamps `captured_at` even then, so the
 * stamp proves nothing. Nothing is known when it is not online and reports neither a supply nor a tray.
 */
export const noAnswerYet = (status: PrinterStatus | undefined): boolean =>
  !status || (status.online == null && !status.markers?.length && !status.trays?.length);

/** A supply is low or empty: the page printer's counterpart of "tape running out". */
export const runningOut = (status: PrinterStatus | undefined): boolean =>
  !!status?.markers?.some((m) => m.low || m.empty);

/** All supplies of a page printer; wraps, so many or long ones never push the card wider. */
export function MarkerList({ markers }: { markers: PrinterStatus["markers"] }) {
  const { t } = useLingui();
  if (!markers || markers.length === 0) return <span className="text-ink-2">{t`No supplies reported`}</span>;
  return (
    <ul className="flex min-w-0 flex-wrap gap-x-4 gap-y-1">
      {markers.map((marker, i) => (
        <li key={`${marker.name}-${i}`} className="min-w-0">
          <MarkerSwatch marker={marker} />
        </li>
      ))}
    </ul>
  );
}

/** The reason keywords of a page printer's state (`PrinterView.reasons`) as words; unknown keywords stay verbatim. */
export function ReasonLine({ reasons }: { reasons: string[] }) {
  const word = useReasonWord();
  if (reasons.length === 0) return null;
  return <span className="min-w-0 break-words text-small text-ink-2">{reasons.map(word).join(" · ")}</span>;
}

/**
 * What to do about "Not monitored": the status is never read because status discovery is off. An admin
 * gets the way to the printer settings; `linked` is false inside a card, which is itself a link.
 */
export function NotMonitoredHint({ linked }: { linked: boolean }) {
  const { t } = useLingui();
  const admin = useSession().scope === "admin";
  return (
    <span className="flex min-w-0 flex-col items-start text-small text-ink-2">
      <span className="[overflow-wrap:anywhere]">{t`Turn on status discovery in the printer settings`}</span>
      {linked && admin && (
        <Link to="/settings/printers" className="inline-flex min-h-11 items-center font-bold text-link underline underline-offset-2">
          {t`Open the printer settings`}
        </Link>
      )}
    </span>
  );
}
