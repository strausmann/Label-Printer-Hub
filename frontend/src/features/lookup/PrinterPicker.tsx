// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useLingui } from "@lingui/react/macro";
import { useState } from "react";
import { FIELD } from "../../shell/SignIn";
import { usePrinterWaiting } from "../printers/flags";
import { describePrinter, isPagePrinter, useKindLabel } from "../printers/model";
import type { Printer, PrinterStatus } from "../printers/api";
import { unsupportedRoll, useRollWords } from "../printers/roll";

const PRINTER_KEY = "lph.printer";

const readChoice = (): string | null => {
  try {
    return localStorage.getItem(PRINTER_KEY);
  } catch {
    return null;
  }
};

/**
 * The printer to print on: the one chosen last time (a per-browser convenience), else the
 * first enabled one. A remembered printer that is gone is ignored. A printer that holds a roll the hub cannot print on
 * (`statuses`, #391) is passed over for the first one that can print; when none can, the choice stays and the hint says why.
 */
export function usePrinterChoice(printers: Printer[] | undefined, statuses?: ReadonlyMap<string, PrinterStatus>) {
  const [chosen, setChosen] = useState<string | null>(readChoice);
  const usable = (printers ?? []).filter((p) => p.enabled);
  const preferred = usable.find((p) => p.id === chosen) ?? usable[0] ?? null;
  const printable = (p: Printer) => unsupportedRoll(statuses?.get(p.id)) === null;
  const selected = preferred && !printable(preferred) ? (usable.find(printable) ?? preferred) : preferred;
  const choose = (id: string) => {
    setChosen(id);
    try {
      localStorage.setItem(PRINTER_KEY, id);
    } catch {
      /* not remembered */
    }
  };
  return { usable, selected, choose };
}

/** "Office laser · Page printer · Stopped": the kind always, the state once the printer's status is known. */
function usePrinterOptionText(): (printer: Printer, status: PrinterStatus | undefined) => string {
  const { t } = useLingui();
  const states = useKindLabel();
  const rollWords = useRollWords();
  // The same `Waiting` as the card and the notification, so the option names the same state (#376).
  const waitingOf = usePrinterWaiting();
  return (printer, status) => {
    const page = isPagePrinter(printer, status);
    const kind = page ? t({ message: "Page printer", context: "printer kind" }) : t({ message: "Tape printer", context: "printer kind" });
    const parts = [printer.name, kind];
    if (status) parts.push(states[describePrinter(printer, status, false, waitingOf(printer.id, status)).kind]);
    // Not offered for printing, with the reason in the option itself (#391); the hub's 409 stays the backstop.
    const roll = page ? null : unsupportedRoll(status);
    if (roll) parts.push(rollWords(roll).unsupported);
    return parts.join(" · ");
  };
}

export function PrinterPicker({
  printers,
  value,
  onChange,
  loading,
  statuses,
}: {
  printers: Printer[];
  value: string | null;
  onChange: (id: string) => void;
  loading: boolean;
  /** Their latest statuses, for the state words in the list. */
  statuses?: ReadonlyMap<string, PrinterStatus>;
}) {
  const { t } = useLingui();
  const optionText = usePrinterOptionText();
  const rollWords = useRollWords();
  const selectedRoll = unsupportedRoll(value ? statuses?.get(value) : undefined);
  return (
    <label className="flex flex-col gap-1.5">
      <span className="font-bold">{t`Printer`}</span>
      <select
        className={FIELD}
        value={value ?? ""}
        disabled={printers.length === 0}
        onChange={(e) => onChange(e.target.value)}
      >
        {printers.length === 0 && <option value="">{loading ? t`Loading…` : t`No printer available`}</option>}
        {printers.map((p) => (
          <option key={p.id} value={p.id} disabled={!isPagePrinter(p, statuses?.get(p.id)) && unsupportedRoll(statuses?.get(p.id)) !== null}>
            {optionText(p, statuses?.get(p.id))}
          </option>
        ))}
      </select>
      {selectedRoll && <span role="status" className="text-small text-bad">{rollWords(selectedRoll).unsupported}. {rollWords(selectedRoll).hint}.</span>}
    </label>
  );
}
