// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useLingui } from "@lingui/react/macro";
import { Link } from "@tanstack/react-router";
import { Fragment } from "react";
import { StatusBadge } from "../../shell/StatusBadge";
import type { Printer, PrinterStatus } from "./api";
import { PauseReason } from "./PauseReason";
import { formatAge } from "./age";
import { useFlagText, usePrinterWaiting } from "./flags";
import { describePrinter, isPagePrinter, staleAgeSeconds, statusIsUnknown, tapeWidthOf, useKindLabel } from "./model";
import { MarkerList, noAnswerYet, NotMonitoredHint, ReasonLine, ReportedEmptyLine } from "./PageStatus";
import { unsupportedRoll, useRollWords, type UnsupportedRoll } from "./roll";
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
  const waitingOf = usePrinterWaiting();
  const view = describePrinter(printer, status, printing, waitingOf(printer.id, status));
  const page = isPagePrinter(printer, status);
  const unknown = statusIsUnknown(status);
  const age = staleAgeSeconds(status);
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
      {view.detail && <span className="text-small text-ink-2">{view.detail}</span>}
      <FlagLine flags={view.flags} />
      <RollLine roll={view.roll} />
      {view.kind === "paused" && <PauseReason pause={printer.pause} />}
      {view.kind === "not_polled" && <NotMonitoredHint printer={printer} page={page} linked={false} />}
      {typeof age === "number" && (
        <span className="text-small text-ink-2 [overflow-wrap:anywhere]">{t`Last status ${ageWord}`}</span>
      )}
      <ReasonLine reasons={view.reasons} />
      <ReportedEmptyLine names={view.reportedEmpty} />
      <span className="mt-auto min-w-0 text-small">
        {unknown ? (
          <span className="text-ink-2">{page ? t`Supplies not known` : t`Tape not known`}</span>
        ) : !page ? (
          <TapeSwatch widthMm={tapeWidthOf(status)} colour={status?.tape_colour} probed={status?.captured_at != null} offline={status?.online === false} roll={unsupportedRoll(status)} />
        ) : noAnswerYet(status) ? (
          <span className="text-ink-2">{t`No answer yet`}</span>
        ) : (
          <MarkerList markers={status?.markers} />
        )}
      </span>
    </Link>
  );
}

/**
 * A tape printer's error flags in words, joined " · " (#376); a flag without words of its own names itself in a
 * quieter tone. Nothing for a printer without flags.
 */
export function FlagLine({ flags, as: Tag = "span" }: { flags: readonly string[]; as?: "span" | "p" }) {
  const flagText = useFlagText();
  if (flags.length === 0) return null;
  return (
    <Tag className="m-0 text-small text-ink-2 [overflow-wrap:anywhere]">
      {flags.map((flag, i) => {
        const { headline, detail } = flagText(flag);
        return (
          <Fragment key={flag}>
            {i > 0 && " · "}
            {headline}
            {detail && <span className="text-ink-3"> ({detail})</span>}
          </Fragment>
        );
      })}
    </Tag>
  );
}

/** "Unsupported roll loaded: 29 × 90 mm die-cut labels": why a printer shows a warning while it holds a roll the hub cannot print on yet. */
export function RollLine({ roll, as: Tag = "span" }: { roll: UnsupportedRoll | undefined; as?: "span" | "p" }) {
  const words = useRollWords();
  if (!roll) return null;
  return <Tag className="m-0 text-small text-ink-2 [overflow-wrap:anywhere]">{words(roll).unsupported}</Tag>;
}
