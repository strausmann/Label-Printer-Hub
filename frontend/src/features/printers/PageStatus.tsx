import { useLingui } from "@lingui/react/macro";
import type { PrinterStatus } from "./api";
import { MarkerSwatch } from "./MarkerSwatch";
import { stoppedReasons } from "./model";
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

/** Why a stopped page printer is stopped, as words (unknown keywords stay verbatim). Nothing when it is not stopped. */
export function ReasonLine({ status }: { status: PrinterStatus | undefined }) {
  const word = useReasonWord();
  const reasons = stoppedReasons(status);
  if (reasons.length === 0) return null;
  return <span className="min-w-0 break-words text-small text-ink-2">{reasons.map((r) => word(r.keyword)).join(" · ")}</span>;
}
