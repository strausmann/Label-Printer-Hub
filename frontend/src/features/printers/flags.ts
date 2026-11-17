// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { msg } from "@lingui/core/macro";
import type { MessageDescriptor } from "@lingui/core";
import { useLingui } from "@lingui/react";
import { useQuery } from "@tanstack/react-query";
import { useCallback } from "react";
import { jobTitle } from "../jobs/model";
import { notificationJobsQuery } from "../notifications/jobsQuery";
import type { Job } from "./api";
import { useCoverRefusals, type CoverRefusal } from "./coverRefusals";
import type { Translate } from "./reasons";

/*
 * The RFC 3805 error flags a tape printer reports (`PrinterStatus.error_flags`, the names of
 * `snmp_helper._ERROR_BITS`). The hub sends the raw names; the words live here (#376).
 */

export type FlagSeverity = "warning" | "error";

/** A flag's severity when nothing waits to print; a flag not listed is an error. */
export const FLAG_SEVERITY: Readonly<Record<string, FlagSeverity>> = {
  lowPaper: "warning",
  noPaper: "error",
  lowToner: "warning",
  noToner: "error",
  doorOpen: "warning",
  jammed: "error",
  offline: "error",
  serviceRequested: "error",
  inputTrayMissing: "error",
  outputTrayMissing: "error",
  markerSupplyMissing: "error",
  outputFull: "error",
  inputTrayEmpty: "error",
  overduePreventMaint: "warning",
};

/** Whether something waits to print on a printer, and which label the sentence names. */
export interface Waiting {
  waiting: boolean;
  /** The title of the job that waits (the oldest queued or printing one), else the refused print's; "" when none is known. */
  job: string;
  /** Nothing is queued or printing, but a print to this printer was refused because of its open cover. */
  refused: boolean;
  /** The printer's latest finished job was refused because of the roll in it (409 `media_type_mismatch`). */
  rollRefused?: boolean;
}

export const NOT_WAITING: Waiting = { waiting: false, job: "", refused: false };

const time = (iso: string): number => {
  const ms = Date.parse(iso);
  return Number.isNaN(ms) ? 0 : ms;
};

/**
 * A job of the printer is queued or printing (the oldest of them by `created_at` is named), or a print to it was refused
 * because of its open cover (`coverRefusals.ts`).
 */
export function printerWaiting(printerId: string, jobs: readonly Job[], refusals: Readonly<Record<string, CoverRefusal>>): Waiting {
  const refusal = Object.hasOwn(refusals, printerId) ? refusals[printerId] : undefined;
  const active = jobs
    .filter((j) => j.printer_id === printerId && (j.state === "queued" || j.state === "printing"))
    .sort((a, b) => time(a.created_at) - time(b.created_at));
  const first = active[0];
  // The newest finished job decides: a later print that went through means the refusal is old news.
  const finished = jobs
    .filter((j) => j.printer_id === printerId && (j.state === "done" || j.state === "failed" || j.state === "failed_restart"))
    .sort((a, b) => time(b.updated_at) - time(a.updated_at))[0];
  const rollRefused = finished?.state === "failed" && (finished.error ?? "").startsWith("media_type_mismatch");
  const extra = rollRefused ? { rollRefused: true } : {};
  if (first) return { waiting: true, job: jobTitle(first) ?? "", refused: false, ...extra };
  if (refusal) return { waiting: true, job: refusal.title, refused: true, ...extra };
  return rollRefused ? { ...NOT_WAITING, ...extra } : NOT_WAITING;
}

/** An open cover is a warning while nothing waits to print, and an error once something does; every other flag has its fixed severity. */
export function flagSeverity(flag: string, w: Waiting): FlagSeverity {
  if (flag === "doorOpen") return w.waiting ? "error" : "warning";
  return Object.hasOwn(FLAG_SEVERITY, flag) ? FLAG_SEVERITY[flag]! : "error";
}

const HEADLINES: Readonly<Record<string, MessageDescriptor>> = {
  doorOpen: msg`Cover open — close it to print`,
  noPaper: msg`No tape or paper — load it to print`,
  lowPaper: msg`Tape or paper running low`,
  jammed: msg`Tape jammed — clear it to print`,
  offline: msg`The printer reports itself offline`,
  serviceRequested: msg`The printer asks for service`,
  noToner: msg`Ink or toner empty`,
  lowToner: msg`Ink or toner low`,
  inputTrayMissing: msg`Input tray missing`,
  outputTrayMissing: msg`Output tray missing`,
  markerSupplyMissing: msg`Supply missing`,
  outputFull: msg`Output tray full`,
  inputTrayEmpty: msg`Input tray empty`,
  overduePreventMaint: msg`Maintenance due`,
};

const UNKNOWN = msg`The printer reports a problem.`;

/** The words for a flag: a sentence of its own, or for a flag we have none for a generic one with the flag as the detail. */
export function flagText(flag: string, t: Translate): { headline: string; detail: string | null } {
  const known = Object.hasOwn(HEADLINES, flag) ? HEADLINES[flag] : undefined;
  return known ? { headline: t(known), detail: null } : { headline: t(UNKNOWN), detail: flag };
}

/** `flagText` bound to the active language, for components. */
export function useFlagText(): (flag: string) => { headline: string; detail: string | null } {
  const { _ } = useLingui();
  return useCallback((flag: string) => flagText(flag, _), [_]);
}

/**
 * `printerWaiting` for components: the jobs the notification centre reads (same query key, so the card, the detail page,
 * the overview row and the entry decide from the same data) and the cover refusals of this tab.
 */
export function usePrinterWaiting(): (printerId: string) => Waiting {
  const jobs = useQuery(notificationJobsQuery());
  const refusals = useCoverRefusals();
  const data = jobs.data;
  return useCallback((printerId: string) => printerWaiting(printerId, data ?? [], refusals), [data, refusals]);
}
