import { useLingui } from "@lingui/react/macro";
import { useState } from "react";
import { ApiError } from "../../api/client";
import { FIELD } from "../../shell/SignIn";
import type { Printer } from "../printers/api";

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

export function PrinterPicker({
  printers,
  value,
  onChange,
  loading,
}: {
  printers: Printer[];
  value: string | null;
  onChange: (id: string) => void;
  loading: boolean;
}) {
  const { t } = useLingui();
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
            {p.name}
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
