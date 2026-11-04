import { useLingui } from "@lingui/react/macro";
import type { BadgeState } from "../../shell/StatusBadge";
import type { Job, Printer, PrinterStatus } from "./api";

export type PrinterKind = "paused" | "offline" | "error" | "printing" | "ready" | "unknown";

export interface PrinterView {
  kind: PrinterKind;
  badge: BadgeState;
  /** Text from the API that explains the state (probe error, error flags); never invented. */
  detail: string | null;
}

/**
 * What the operator can act on wins: a paused printer says Paused even when it is also
 * offline. The API has no reason text for a pause, so none is shown.
 */
export function describePrinter(printer: Printer, status: PrinterStatus | undefined, printing: boolean): PrinterView {
  if (printer.paused) return { kind: "paused", badge: "warn", detail: null };
  if (status?.online === false) {
    return { kind: "offline", badge: "bad", detail: status.last_error ?? status.error_state ?? null };
  }
  if (status?.error_state) return { kind: "error", badge: "bad", detail: status.error_state };
  if (printing) return { kind: "printing", badge: "ok", detail: null };
  if (status?.online === true) return { kind: "ready", badge: "ok", detail: null };
  return { kind: "unknown", badge: "idle", detail: status?.note ?? null };
}

export function useKindLabel(): Record<PrinterKind, string> {
  const { t } = useLingui();
  return {
    paused: t`Paused`,
    offline: t`Offline`,
    error: t`Problem`,
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

export const TAPE_COLOURS = ["white", "yellow", "green", "blue", "red"] as const;
export type TapeColour = (typeof TAPE_COLOURS)[number];

export interface TapeInfo {
  widthMm: number | null;
  /** Colour word as reported (`blue`), or null when the API does not say. */
  colourName: string | null;
  /** The colour when it is one of the five swatches we can draw. */
  colour: TapeColour | null;
}

/**
 * `tape_loaded` is free text: `12mm` today, `12mm laminated blue/white` in the documented
 * form (tape colour before the slash, text colour after it). Anything not found stays null.
 */
export function parseTape(tapeLoaded: string | null | undefined): TapeInfo | null {
  if (!tapeLoaded || tapeLoaded.trim() === "") return null;
  const width = /(\d+(?:[.,]\d+)?)\s*mm/i.exec(tapeLoaded);
  const colour = /([a-z]+)\s*\/\s*[a-z]+/i.exec(tapeLoaded);
  const colourName = colour?.[1]?.toLowerCase() ?? null;
  return {
    widthMm: width ? Number(width[1]!.replace(",", ".")) : null,
    colourName,
    colour: TAPE_COLOURS.find((c) => c === colourName) ?? null,
  };
}

export function useColourNames(): Record<TapeColour, string> {
  const { t } = useLingui();
  return { white: t`White`, yellow: t`Yellow`, green: t`Green`, blue: t`Blue`, red: t`Red` };
}
