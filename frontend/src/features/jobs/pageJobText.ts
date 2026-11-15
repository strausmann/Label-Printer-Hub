// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useLingui } from "@lingui/react/macro";
import { usePrinterStatus } from "../printers/api";
import { printerStopReasons } from "../printers/model";
import { useReasonWord } from "../printers/reasons";
import type { Job } from "./api";
import { pageInfoOf } from "./model";
import { usePageJobState } from "./pageJobState";

/** Job-level reasons that say nothing beyond "stopped": left out of the words after it. */
const NOISE = new Set(["none", "printer-stopped"]);

export interface PageJobStatus {
  text: string;
  /** Stopped at the printer: needs someone, so it is set apart from the calm states. */
  stopped: boolean;
}

/**
 * Where a page job in print stands at the printer, in words; null for any other job. The
 * sub-state arrives with the live events and the reconnect snapshot. Until one has been seen the
 * text says "at the printer" and does not guess a sub-state.
 *
 * A printer reports why it stopped as printer reasons (toner empty); the job's own reasons
 * usually say only "printer-stopped". So when the job names no cause, the printer's blocking
 * reasons from its status are named instead.
 */
export function usePageJobStatus(job: Job): PageJobStatus | null {
  const { t } = useLingui();
  const reasonWord = useReasonWord();
  const live = usePageJobState(job.id);
  const active = job.state === "printing" && pageInfoOf(job) !== null;
  const stopped = active && live?.atPrinter === "stopped";
  const jobReasons = stopped ? live.reasons.filter((r) => !NOISE.has(r)) : [];
  const printerStatus = usePrinterStatus(job.printer_id, stopped && jobReasons.length === 0);
  if (!active) return null;
  switch (live?.atPrinter) {
    case "waiting":
      return { text: t`Waiting at the printer`, stopped: false };
    case "printing":
      return { text: t({ message: "Printing", context: "page job at the printer" }), stopped: false };
    case "stopped": {
      const keywords = jobReasons.length > 0 ? jobReasons : printerStopReasons(printerStatus.data);
      const head = t`Stopped at the printer`;
      return { text: keywords.length > 0 ? `${head} · ${keywords.map(reasonWord).join(", ")}` : head, stopped: true };
    }
    default:
      return { text: t`At the printer`, stopped: false };
  }
}
