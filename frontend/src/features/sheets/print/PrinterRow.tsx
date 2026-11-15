// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { plural } from "@lingui/core/macro";
import { useLingui } from "@lingui/react/macro";
import { StatusBadge } from "../../../shell/StatusBadge";
import type { Printer, PrinterStatus } from "../../printers/api";
import { describePrinter, statusIsUnknown, useKindLabel, type PrinterKind } from "../../printers/model";
import { MarkerList, noAnswerYet, ReasonLine } from "../../printers/PageStatus";

/** States in which a print waits in the hub's queue instead of starting at once. */
const WAITS: readonly PrinterKind[] = ["stopped", "error", "offline", "paused"];
export const printerWaits = (kind: PrinterKind): boolean => WAITS.includes(kind);

/** The page printer in one block: its state as a shape and a word, the supplies, and other computers' jobs ahead of ours. */
export function PrinterRow({ printer, status }: { printer: Printer; status: PrinterStatus | undefined }) {
  const { t } = useLingui();
  const kinds = useKindLabel();
  const view = describePrinter(printer, status, false);
  const ahead = status?.jobs_ahead ?? 0;
  const unanswered = noAnswerYet(status);
  return (
    <div className="flex min-w-0 flex-col gap-2">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="font-bold [overflow-wrap:anywhere]">{printer.name}</span>
        <StatusBadge state={view.badge} label={kinds[view.kind]} />
        <ReasonLine reasons={view.reasons} />
      </div>
      {statusIsUnknown(status) ? (
        <span className="text-small text-ink-2">{t`Supplies not known`}</span>
      ) : unanswered ? <span className="text-small text-ink-2">{t`No answer yet`}</span> : <MarkerList markers={status?.markers} />}
      {ahead > 0 && (
        <p className="text-small text-ink-2">
          {plural(ahead, { one: "# job from another computer ahead", other: "# jobs from other computers ahead" })}
        </p>
      )}
    </div>
  );
}
