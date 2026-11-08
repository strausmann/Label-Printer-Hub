import { useLingui } from "@lingui/react/macro";
import { useReasonWord } from "../printers/reasons";
import type { Job } from "./api";
import { pageInfoOf } from "./model";
import { usePageJobState } from "./pageJobState";

/** Job-level reasons that say nothing beyond "stopped": left out of the words after it. */
const NOISE = new Set(["none", "printer-stopped"]);

/**
 * Where a page job in print stands at the printer, in words; null for any other job. The
 * sub-state arrives with the live events and the reconnect snapshot. Until one has been seen the
 * text says "at the printer" and does not guess a sub-state.
 */
export function usePageJobStatus(job: Job): string | null {
  const { t } = useLingui();
  const reasonWord = useReasonWord();
  const live = usePageJobState(job.id);
  if (job.state !== "printing" || pageInfoOf(job) === null) return null;
  switch (live?.atPrinter) {
    case "waiting":
      return t`Waiting at the printer`;
    case "printing":
      return t({ message: "Printing", context: "page job at the printer" });
    case "stopped": {
      const words = live.reasons.filter((r) => !NOISE.has(r)).map(reasonWord);
      const head = t`Stopped at the printer`;
      return words.length > 0 ? `${head} · ${words.join(", ")}` : head;
    }
    default:
      return t`At the printer`;
  }
}
