import { useLingui } from "@lingui/react/macro";
import { useState } from "react";
import { ApiError } from "../../api/client";
import { FIELD } from "../../shell/SignIn";
import { describePrinter, isPagePrinter, useKindLabel } from "../printers/model";
import type { Printer, PrinterStatus } from "../printers/api";

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
 * first enabled one. A remembered printer that is gone is ignored.
 */
export function usePrinterChoice(printers: Printer[] | undefined) {
  const [chosen, setChosen] = useState<string | null>(readChoice);
  const usable = (printers ?? []).filter((p) => p.enabled);
  const selected = usable.find((p) => p.id === chosen) ?? usable[0] ?? null;
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
  return (printer, status) => {
    const page = isPagePrinter(printer, status);
    const kind = page ? t({ message: "Page printer", context: "printer kind" }) : t({ message: "Tape printer", context: "printer kind" });
    const parts = [printer.name, kind];
    if (status) parts.push(states[describePrinter(printer, status, false).kind]);
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
          <option key={p.id} value={p.id}>
            {optionText(p, statuses?.get(p.id))}
          </option>
        ))}
      </select>
    </label>
  );
}

/** The server's own wording when it gave one (offline, no tape, cover open …), else a plain fallback. */
export function usePrintErrorText(): (error: unknown) => string {
  const { t } = useLingui();
  return (error) => {
    if (error instanceof ApiError) {
      if (error.status === 0) return t`The server cannot be reached.`;
      if (error.detail && !/^HTTP \d+$/.test(error.detail)) return error.detail;
    }
    return t`The labels could not be sent.`;
  };
}
