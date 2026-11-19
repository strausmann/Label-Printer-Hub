// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useLingui } from "@lingui/react/macro";
import type { Printer } from "./api";
import { isKnownReason, useReasonWord } from "./reasons";

/**
 * Why a printer is paused, in words. Known codes get a sentence (a page printer's keywords get
 * their reason words); an unknown code is shown verbatim in mono so nobody is told something
 * the hub did not say. Renders nothing for a printer without pause details (e.g. an older hub).
 */
export function PauseReason({ pause }: { pause: Printer["pause"] }) {
  const { t } = useLingui();
  const word = useReasonWord();
  if (!pause) return null;
  const known: Record<string, string> = {
    user: t`Paused by user`,
    tape_empty: t`Tape is empty`,
    cover_open: t`Cover is open`,
    printer_cover_open: t`Cover is open`,
    tape_mismatch: t`Wrong tape loaded`,
    offline: t`Printer is offline`,
    printer_offline: t`Printer is offline`,
    // #389: a blocking bit the tape printer reported (jam, service request, …), and a QL roll of
    // die-cut labels (the hub prints on continuous tape only).
    printer_error: t`The printer reports an error — check the printer`,
    media_type_mismatch: t`Die-cut labels loaded — put in a continuous roll`,
    // #393: a print the printer did not confirm in time may still finish.
    outcome_unknown: t`A print may not have finished — check the printer`,
    // The hub's own hold while a page printer's status check is not running (it retries).
    "status-unavailable": t`Waiting for the printer's status check`,
  };
  // A page printer pauses with its own keyword (`toner-empty`); words for those, the code only as a last resort.
  const text = Object.hasOwn(known, pause.reason_code)
    ? known[pause.reason_code]
    : isKnownReason(pause.reason_code)
      ? word(pause.reason_code)
      : null;
  return (
    <span className="text-small text-ink-2">
      {text ?? <code className="font-mono">{pause.reason_code}</code>}
    </span>
  );
}
