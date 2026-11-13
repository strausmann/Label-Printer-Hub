import { useLingui } from "@lingui/react/macro";
import { Link } from "@tanstack/react-router";
import type { ReactNode } from "react";
import { useInfo, useSession } from "../../app/session";
import { docsUrl } from "../about/docsLink";
import type { Printer, PrinterStatus } from "./api";
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

/** The getting-started section that shows how an admin turns status discovery on until the form can (#296). */
export const STATUS_DISCOVERY_DOC = "docs/getting-started.md#turn-on-status-discovery";

const HINT_LINK = "inline-flex min-h-11 items-center font-bold text-link underline underline-offset-2";

/**
 * What to do about "Not monitored": no status producer runs for the printer. For a tape printer that
 * means status discovery (SNMP) is off, which only the admin API can change today (#296); an enabled
 * page printer is unpolled only when the hub could not wire it, so an admin checks its address; a
 * printer switched off in the hub is not read at all. `linked` is false inside a card, which is itself
 * a link.
 */
export function NotMonitoredHint({ printer, page, linked }: { printer: Printer; page: boolean; linked: boolean }) {
  const { t } = useLingui();
  const admin = useSession().scope === "admin";
  const howTo = docsUrl(useInfo().data?.source_url, STATUS_DISCOVERY_DOC);
  let text: string;
  let link: ReactNode = null;
  if (!printer.enabled) {
    text = t`The printer is switched off in the hub. An admin can switch it on in the printer settings.`;
    link = <SettingsLink />;
  } else if (page) {
    text = t`The hub cannot read this printer's status. An admin can check its address in the printer settings.`;
    link = <SettingsLink />;
  } else {
    text = t`Status discovery is off for this printer. An admin can turn it on through the admin API.`;
    link = howTo ? (
      <a href={howTo} target="_blank" rel="noopener noreferrer" className={HINT_LINK}>
        {t`How to turn on status discovery`}
      </a>
    ) : null;
  }
  return (
    <span className="flex min-w-0 flex-col items-start text-small text-ink-2">
      <span className="[overflow-wrap:anywhere]">{text}</span>
      {linked && admin && link}
    </span>
  );
}

function SettingsLink() {
  const { t } = useLingui();
  return (
    <Link to="/settings/printers" className={HINT_LINK}>
      {t`Open the printer settings`}
    </Link>
  );
}
