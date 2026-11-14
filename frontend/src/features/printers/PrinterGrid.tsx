// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useLingui } from "@lingui/react/macro";
import { usePrinters, usePrinterStatuses, useRecentJobs } from "./api";
import { PrinterCard } from "./PrinterCard";

/** The printer cards, shared by the Printers page and the Overview. */
export function PrinterGrid() {
  const { t } = useLingui();
  const printers = usePrinters();
  const statuses = usePrinterStatuses(printers.data);
  // A jobs failure only costs the "Printing" state; the cards still show everything else.
  const jobs = useRecentJobs();
  const busy = new Set((jobs.data ?? []).filter((j) => j.state === "printing").map((j) => j.printer_id));

  if (printers.isPending) return <p role="status" className="text-ink-2">{t`Loading…`}</p>;
  if (printers.isError) return <p role="alert" className="text-bad">{t`The printers could not be loaded.`}</p>;
  if (printers.data.length === 0) return <p className="text-ink-2">{t`No printers yet.`}</p>;
  return (
    <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
      {printers.data.map((printer) => (
        <li key={printer.id} className="min-w-0">
          <PrinterCard printer={printer} status={statuses.get(printer.id)} printing={busy.has(printer.id)} />
        </li>
      ))}
    </ul>
  );
}
