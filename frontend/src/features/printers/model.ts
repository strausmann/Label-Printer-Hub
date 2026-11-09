import { useLingui } from "@lingui/react/macro";
import type { BadgeState } from "../../shell/StatusBadge";
import type { Job, Printer, PrinterStatus } from "./api";

export type PrinterKind = "paused" | "stale" | "not_polled" | "offline" | "error" | "stopped" | "printing" | "ready" | "unknown";

export interface PrinterView {
  kind: PrinterKind;
  badge: BadgeState;
  /** Text from the API that explains the state (probe error, error flags); never invented. */
  detail: string | null;
  /** Page printers: why a printer is stopped or has a problem (`printer-state-reasons` keywords, in the order sent). */
  reasons: string[];
}

/** A page (IPP) printer: the list carries `backend`, the status `kind` confirms it. */
export const isPagePrinter = (printer: Printer, status?: PrinterStatus): boolean =>
  printer.backend === "ipp" || status?.kind === "page";

type Reason = NonNullable<PrinterStatus["state_reasons"]>[number];

/**
 * The reasons worth naming while a page printer is stopped: the blocking ones, or, when none
 * blocks, every warning and error (a `report` entry is information, not a cause). Empty for a
 * printer that is not stopped.
 */
function stoppedReasons(status: PrinterStatus | undefined): Reason[] {
  if (status?.printer_state !== "stopped") return [];
  const all = status.state_reasons ?? [];
  const blocking = all.filter((r) => r.blocking);
  return blocking.length > 0 ? blocking : all.filter((r) => r.severity !== "report");
}

/**
 * The keywords that say why a page printer cannot print right now: what a stopped printer names
 * (`describePrinter`), else its blocking reasons. Empty when the status names none. A job that is
 * stopped at the printer carries only job-level reasons ("printer-stopped"); this is the cause.
 */
export function printerStopReasons(status: PrinterStatus | undefined): string[] {
  const stopped = stoppedReasons(status).map((r) => r.keyword);
  if (stopped.length > 0) return stopped;
  return (status?.state_reasons ?? []).filter((r) => r.blocking).map((r) => r.keyword);
}

/** The status is not a reading of the printer now: nobody polls it, or the last probe is too old. */
export const unknownKind = (status: PrinterStatus | undefined): "not_polled" | "stale" | null =>
  status?.polled === false ? "not_polled" : status?.stale === true ? "stale" : null;

export const statusIsUnknown = (status: PrinterStatus | undefined): boolean => unknownKind(status) !== null;

/**
 * What the operator can act on wins: a paused printer says Paused even when it is also
 * offline. The reason for a pause comes from `printer.pause` (see PauseReason).
 */
export function describePrinter(printer: Printer, status: PrinterStatus | undefined, printing: boolean): PrinterView {
  if (printer.paused) return { kind: "paused", badge: "warn", detail: null, reasons: [] };
  // Before any `online` branch: a status nobody refreshes says nothing about the printer (#227).
  const unknown = unknownKind(status);
  if (unknown) return { kind: unknown, badge: "idle", detail: null, reasons: [] };
  if (status?.online === false) {
    return { kind: "offline", badge: "bad", detail: status.last_error ?? status.error_state ?? null, reasons: [] };
  }
  const page = isPagePrinter(printer, status);
  if (page && status?.printer_state === "stopped") {
    const reasons = stoppedReasons(status);
    const serious = reasons.some((r) => r.blocking || r.severity === "error");
    return { kind: "stopped", badge: serious ? "bad" : "warn", detail: null, reasons: reasons.map((r) => r.keyword) };
  }
  // After the stopped case: a stopped page printer's `error_state` only repeats its reason keywords.
  if (status?.error_state) {
    if (page) {
      // The hub copies a blocking reason keyword into `error_state`; name it in words, like a stopped printer's.
      const blocking = (status.state_reasons ?? []).filter((r) => r.blocking).map((r) => r.keyword);
      return { kind: "error", badge: "bad", detail: null, reasons: blocking.length > 0 ? blocking : [status.error_state] };
    }
    return { kind: "error", badge: "bad", detail: status.error_state, reasons: [] };
  }
  // A page printer can be busy with another computer's job, which the hub's queue never sees.
  if (printing || (page && status?.printer_state === "printing")) {
    return { kind: "printing", badge: "ok", detail: null, reasons: [] };
  }
  if (status?.online === true) return { kind: "ready", badge: "ok", detail: null, reasons: [] };
  return { kind: "unknown", badge: "idle", detail: status?.note ?? null, reasons: [] };
}

export function useKindLabel(): Record<PrinterKind, string> {
  const { t } = useLingui();
  return {
    paused: t`Paused`,
    stale: t`Status unknown`,
    not_polled: t`Not monitored`,
    offline: t`Offline`,
    error: t`Problem`,
    stopped: t`Stopped`,
    printing: t`Printing`,
    ready: t`Ready`,
    unknown: t`No status yet`,
  };
}

export function useJobStateBadge(): (state: string) => { badge: BadgeState; label: string } {
  const { t } = useLingui();
  return (state) => {
    switch (state) {
      case "queued":
        return { badge: "idle", label: t`Queued` };
      case "printing":
        return { badge: "ok", label: t`Printing` };
      case "done":
        return { badge: "ok", label: t`Done` };
      case "failed":
        return { badge: "bad", label: t`Failed` };
      case "failed_restart":
        return { badge: "bad", label: t`Interrupted by a restart` };
      case "cancelled":
        return { badge: "idle", label: t`Cancelled` };
      default:
        return { badge: "idle", label: state };
    }
  };
}

export const isFailed = (job: Job) => job.state === "failed" || job.state === "failed_restart";

/* ---- tape ------------------------------------------------------------------------------ */

/** The colours an operator can give a roll; the printer reports none of them over the network. */
export const TAPE_COLOURS = ["white", "yellow", "green", "blue", "red", "black", "clear"] as const;
export type TapeColour = (typeof TAPE_COLOURS)[number];

/**
 * The loaded width in mm: the reported number, else the leading `12mm` of the free text
 * (`tape_loaded`). Null when none is known; a colour is never read from the text any more.
 */
export function tapeWidthOf(status: Pick<PrinterStatus, "tape_loaded" | "tape_width_mm"> | undefined): number | null {
  if (!status) return null;
  if (typeof status.tape_width_mm === "number") return status.tape_width_mm;
  const match = /(\d+(?:[.,]\d+)?)\s*mm/i.exec(status.tape_loaded ?? "");
  return match ? Number(match[1]!.replace(",", ".")) : null;
}

export function useColourNames(): Record<TapeColour, string> {
  const { t } = useLingui();
  return { white: t`White`, yellow: t`Yellow`, green: t`Green`, blue: t`Blue`, red: t`Red`, black: t`Black`, clear: t({ message: "Clear", context: "tape colour" }) };
}
