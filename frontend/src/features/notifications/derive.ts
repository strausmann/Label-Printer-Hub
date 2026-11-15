// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { jobTitle } from "../jobs/model";
import type { Job, Printer, PrinterStatus } from "../printers/api";
import { describePrinter, isFailed, type PrinterKind } from "../printers/model";
import type { SheetSummary } from "../sheets/api";
import type { components } from "../../api/schema.gen";

export type SheetTypeNotice = components["schemas"]["SheetTypeNotice"];

/** Query key of the hub's notices (`GET /api/v1/notices`). */
export const NOTICES_KEY = ["notices"] as const;

export type Severity = "error" | "warning" | "success" | "info";

export interface Notification {
  /** `job:<id>:<state>`, `printer:<id>:<kind>`, `sheet:<code>:unconfirmed` or `sheet-type-verified:<key>:<revision>`: a new state is a new entry. */
  id: string;
  severity: Severity;
  kind: "job" | "printer" | "sheet" | "sheet_type";
  /** Which sentence the component says (`job.failed`, `printer.offline` …); the words live in the component, so they are translated. */
  textKey: string;
  /** The names and numbers the sentence is made of. Empty text means "not known"; the component then says it its own way. */
  values: Record<string, string>;
  /** ISO time: the job's last change, or the moment this browser first saw the condition. */
  at: string;
  target: {
    to: "/jobs/$jobId" | "/printers/$printerId" | "/sheets/$code" | "/sheets/archive";
    params: Record<string, string>;
    /** Search parameters of the target page (the sheet archive filters by `type`). */
    search?: { type: string };
  };
  /** A failed job that a later retry printed: information now, and no longer "needs attention". */
  resolved?: boolean;
}

export interface DeriveInput {
  jobs: Job[];
  printers: Printer[];
  statuses: Record<string, PrinterStatus | undefined>;
  sheets: SheetSummary[];
  /** Entry id → ISO time this browser first saw a printer or sheet condition. */
  firstSeen: Record<string, string>;
  now: number;
}

export const MAX_ENTRIES = 100;
/** Jobs are fetched for this long back; the derivation drops what changed before it too, so a stale answer cannot show old failures. */
export const WINDOW_MS = 24 * 60 * 60 * 1000;

const time = (iso: string): number => {
  const ms = Date.parse(iso);
  return Number.isNaN(ms) ? 0 : ms;
};

/** The id of the job a retry repeats; that job may be gone, and a payload of another shape counts as having none. */
function retryOf(job: Job): string | null {
  const value = (job.payload as Record<string, unknown> | null | undefined)?.retry_of;
  return typeof value === "string" && value !== "" ? value : null;
}

/** Every job that a `done` job repeats, directly or through failed retries in between (failed → failed → done). */
function resolvedByRetry(jobs: Job[]): Set<string> {
  const byId = new Map(jobs.map((j) => [j.id, j]));
  const resolved = new Set<string>();
  for (const done of jobs) {
    if (done.state !== "done") continue;
    // A loop in the data must not hang the page: each job is visited once per walk.
    const walked = new Set<string>([done.id]);
    for (let next = retryOf(done); next !== null && !walked.has(next); ) {
      walked.add(next);
      resolved.add(next);
      const source = byId.get(next);
      next = source ? retryOf(source) : null;
    }
  }
  return resolved;
}

const JOB_SEVERITY: Record<string, Severity> = { queued: "info", printing: "info", done: "success", cancelled: "info" };

function jobEntry(job: Job, printers: Map<string, Printer>, resolved: Set<string>): Notification | null {
  let severity: Severity;
  let textKey: string;
  let isResolved = false;
  if (isFailed(job)) {
    isResolved = resolved.has(job.id);
    severity = isResolved ? "info" : "error";
    textKey = isResolved ? "job.retried" : "job.failed";
  } else {
    const known = JOB_SEVERITY[job.state];
    if (!known) return null;
    severity = known;
    textKey = `job.${job.state}`;
  }
  return {
    id: `job:${job.id}:${job.state}`,
    severity,
    kind: "job",
    textKey,
    values: {
      title: jobTitle(job) ?? "",
      printer: printers.get(job.printer_id)?.name ?? "",
      ...(textKey === "job.failed" ? { error: job.error ?? "" } : {}),
    },
    at: job.updated_at,
    target: { to: "/jobs/$jobId", params: { jobId: job.id } },
    ...(isResolved ? { resolved: true } : {}),
  };
}

const PRINTER_SEVERITY: Partial<Record<PrinterKind, Severity>> = {
  offline: "error",
  error: "error",
  different_device: "error",
  paused: "warning",
  stale: "warning",
  not_polled: "warning",
};

function printerEntries(
  printer: Printer,
  status: PrinterStatus | undefined,
  printing: boolean,
  firstSeen: Record<string, string>,
  now: number,
): Notification[] {
  const view = describePrinter(printer, status, printing);
  const target: Notification["target"] = { to: "/printers/$printerId", params: { printerId: printer.id } };
  const at = (id: string) => firstSeen[id] ?? new Date(now).toISOString();
  const entries: Notification[] = [];

  // A stopped page printer is an error only for a blocking or error reason; any other stop is a warning.
  const severity = view.kind === "stopped" ? (view.badge === "bad" ? "error" : "warning") : PRINTER_SEVERITY[view.kind];
  if (severity) {
    const id = `printer:${printer.id}:${view.kind}`;
    entries.push({
      id,
      severity,
      kind: "printer",
      textKey: `printer.${view.kind}`,
      values: { printer: printer.name, detail: view.detail ?? "", reasons: view.reasons.join(",") },
      at: at(id),
      target,
    });
  }

  // Supplies are only read from a status that is a reading of the printer now.
  if (status && status.stale !== true && status.polled !== false) {
    const markers = status.markers ?? [];
    const empty = markers.filter((m) => m.empty).map((m) => m.name);
    const low = markers.filter((m) => m.low && !m.empty).map((m) => m.name);
    if (empty.length > 0 || low.length > 0) {
      const id = `printer:${printer.id}:material`;
      entries.push({
        id,
        severity: "warning",
        kind: "printer",
        textKey: "printer.material",
        values: { printer: printer.name, empty: empty.join(", "), low: low.join(", ") },
        at: at(id),
        target,
      });
    }
  }
  return entries;
}

function sheetEntry(sheet: SheetSummary, firstSeen: Record<string, string>, now: number): Notification | null {
  if (sheet.state !== "active" || sheet.unconfirmed <= 0) return null;
  const id = `sheet:${sheet.code}:unconfirmed`;
  return {
    id,
    severity: "warning",
    kind: "sheet",
    textKey: "sheet.unconfirmed",
    values: { count: String(sheet.unconfirmed), code: sheet.code },
    at: firstSeen[id] ?? new Date(now).toISOString(),
    target: { to: "/sheets/$code", params: { code: sheet.code } },
  };
}

export const newestFirst = (a: Notification, b: Notification) => time(b.at) - time(a.at) || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0);

/**
 * The hub's own notices as entries: a shipped sheet type was marked verified or got new dimensions. Information,
 * not a standing condition, so they join the feed after `deriveNotifications` and are never part of its cap. The
 * `code` is the one the hub stored when it wrote the notice (the type's own product code), not derived here.
 */
export function deriveNotices(notices: readonly SheetTypeNotice[]): Notification[] {
  return notices.map((n) => ({
    id: n.id,
    severity: "info",
    kind: "sheet_type",
    textKey: n.kind === "sheet_type_updated" ? "sheet_type.updated" : "sheet_type.verified",
    values: { code: n.code },
    at: n.at,
    target: { to: "/sheets/archive", params: {}, search: { type: n.key } },
  }));
}

/**
 * Everything the notification centre and the overview's "Needs attention" show, from data the server already serves:
 * the print jobs of the last day, the printers with their status, and the sheets. Newest first; at most 100, standing conditions (printer, sheet, unresolved errors) never cut.
 * Pure: the clock is `now`, and the moment a printer or sheet condition began is `firstSeen`.
 */
export function deriveNotifications(input: DeriveInput): Notification[] {
  const { jobs, printers, statuses, sheets, firstSeen, now } = input;
  const byPrinter = new Map(printers.map((p) => [p.id, p]));
  const recent = jobs.filter((j) => now - time(j.updated_at) < WINDOW_MS);
  const resolved = resolvedByRetry(jobs);
  const busy = new Set(recent.filter((j) => j.state === "printing").map((j) => j.printer_id));

  const entries: Notification[] = [];
  for (const job of recent) {
    const entry = jobEntry(job, byPrinter, resolved);
    if (entry) entries.push(entry);
  }
  for (const printer of printers) entries.push(...printerEntries(printer, statuses[printer.id], busy.has(printer.id), firstSeen, now));
  for (const sheet of sheets) {
    const entry = sheetEntry(sheet, firstSeen, now);
    if (entry) entries.push(entry);
  }

  // A standing condition (a printer or sheet entry, an unresolved error) is never displaced by finished or queued
  // jobs: on a busy install 100 newer done jobs would otherwise push it out of the bell and the overview card, and
  // its first-seen time would start over when they aged out. The cap applies to the remainder.
  const standing = entries.filter((e) => e.kind !== "job" || (e.severity === "error" && !e.resolved));
  const standingIds = new Set(standing.map((e) => e.id));
  const rest = entries.filter((e) => !standingIds.has(e.id));
  const kept = [...standing, ...rest.sort(newestFirst).slice(0, Math.max(0, MAX_ENTRIES - standing.length))];
  return kept.sort(newestFirst);
}
