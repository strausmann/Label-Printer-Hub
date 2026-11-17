// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useSyncExternalStore } from "react";
import { ApiError } from "../../api/client";
import type { PrinterStatus } from "./api";
import { normalise } from "./printErrorText";

/*
 * A print refused because the printer's cover is open (#376). It makes the open cover a problem at
 * once, before the next status poll shows the cover, and stays until a new reading of that printer
 * reports the cover closed. Per tab, in memory; no clock: the event decides, not time.
 */

export const COVER_OPEN_CODE = "printer_cover_open";

export interface CoverRefusal {
  /** The label that was refused; "" when the event does not name one. */
  title: string;
}

type Refusals = Readonly<Record<string, CoverRefusal>>;

let refusals: Refusals = {};
/** Printer id → the reading (`captured_at`) that was current when the refusal was first seen next to a status. */
let baseline: Record<string, string> = {};
const listeners = new Set<() => void>();

const without = <T>(record: Readonly<Record<string, T>>, key: string): Record<string, T> =>
  Object.fromEntries(Object.entries(record).filter(([k]) => k !== key));

function commit(next: Refusals): void {
  refusals = next;
  for (const listener of listeners) listener();
}

export function recordCoverRefusal(printerId: string, title: string): void {
  if (printerId === "") return;
  baseline = without(baseline, printerId);
  commit({ ...refusals, [printerId]: { title } });
}

export function clearCoverRefusal(printerId: string): void {
  if (!Object.hasOwn(refusals, printerId)) return;
  baseline = without(baseline, printerId);
  commit(without(refusals, printerId));
}

/** A job event (`job.state_changed`): a job that failed on the open cover records a refusal for its printer. */
export function noteJobEvent(printerId: string | null, data: Record<string, unknown>): void {
  if (printerId && data.to_state === "failed" && data.error_code === COVER_OPEN_CODE) recordCoverRefusal(printerId, "");
}

/**
 * A print of this browser that the hub refused (a label, a cart, a test print): an open cover records a refusal; any
 * other failure none. The envelope's `printer_cover_open` and the problem type `printer-cover-open` are one code.
 */
export function notePrintError(printerId: string, title: string, error: unknown): void {
  if (error instanceof ApiError && error.code !== null && normalise(error.code) === COVER_OPEN_CODE) recordCoverRefusal(printerId, title);
}

/**
 * Called by `useNotifications`, which the shell's bell keeps mounted on every signed-in page; a refusal therefore
 * clears wherever the user is. A page without the shell would keep it until the bell is mounted again.
 *
 * Clears a refusal once a new reading of its printer reports no open cover. The reading current when the refusal was
 * first seen does not count: it can predate the cover opening (the print was refused before the next poll).
 */
export function observeStatuses(statuses: Readonly<Record<string, PrinterStatus | undefined>>): void {
  for (const printerId of Object.keys(refusals)) {
    const status = statuses[printerId];
    if (!status) continue;
    const reading = status.captured_at ?? "";
    if (!Object.hasOwn(baseline, printerId)) {
      baseline = { ...baseline, [printerId]: reading };
      continue;
    }
    if (reading !== baseline[printerId] && !(status.error_flags ?? []).includes("doorOpen")) clearCoverRefusal(printerId);
  }
}

const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => listeners.delete(listener);
};
const snapshot = () => refusals;

/** The refusals of this tab, printer id → refusal. */
export function useCoverRefusals(): Refusals {
  return useSyncExternalStore(subscribe, snapshot);
}

/** Tests: forget every refusal. */
export function resetCoverRefusals(): void {
  baseline = {};
  commit({});
}
