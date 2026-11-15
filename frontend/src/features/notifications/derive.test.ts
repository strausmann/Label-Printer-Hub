// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { describe, expect, it } from "vitest";
import { job, PAGE_PRINTER, pageStatus, PRINTER_A, PRINTER_B, status } from "../test-api";
import type { Job, Printer, PrinterStatus } from "../printers/api";
import type { SheetSummary } from "../sheets/api";
import { deriveNotifications } from "./derive";

const NOW = Date.parse("2026-11-14T12:00:00Z");
const minutesAgo = (m: number) => new Date(NOW - m * 60_000).toISOString();

const A = PRINTER_A as unknown as Printer;
const B = { ...PRINTER_B, paused: false } as unknown as Printer;
const PAGE = PAGE_PRINTER as unknown as Printer;
const J1 = "aaaaaaaa-0000-4000-8000-000000000001";
const J2 = "aaaaaaaa-0000-4000-8000-000000000002";
const J3 = "aaaaaaaa-0000-4000-8000-000000000003";

const mkJob = (id: string, state: string, over: Record<string, unknown> = {}): Job =>
  job(id, A.id, state, { created_at: minutesAgo(30), updated_at: minutesAgo(5), ...over }) as unknown as Job;

interface Input {
  jobs?: Job[];
  printers?: Printer[];
  statuses?: Record<string, PrinterStatus | undefined>;
  sheets?: SheetSummary[];
  firstSeen?: Record<string, string>;
}
const run = (i: Input = {}) =>
  deriveNotifications({ jobs: [], printers: [], statuses: {}, sheets: [], firstSeen: {}, now: NOW, ...i });

const okStatus = (p: Printer, over: Record<string, unknown> = {}) => status(p.id, over) as unknown as PrinterStatus;
const sheet = (code: string, unconfirmed: number): SheetSummary =>
  ({ code, unconfirmed, state: "active", type_key: "t", type_label: "T", free: 1, used: 1, reserved: 0, total: 2, version: 1, label_w: 1, label_h: 1, last_used_at: null }) as SheetSummary;

describe("deriveNotifications: jobs", () => {
  it.each(["queued", "printing"])("a %s job is information that opens the job page", (state) => {
    const [entry, ...rest] = run({ jobs: [mkJob(J1, state, { template_key: "cable" })], printers: [A] });
    expect(rest).toEqual([]);
    expect(entry).toMatchObject({
      id: `job:${J1}:${state}`,
      severity: "info",
      kind: "job",
      textKey: `job.${state}`,
      values: { title: "cable", printer: A.name },
      target: { to: "/jobs/$jobId", params: { jobId: J1 } },
    });
  });

  it("a done job is a success", () => {
    const [entry] = run({ jobs: [mkJob(J1, "done")], printers: [A] });
    expect(entry).toMatchObject({ id: `job:${J1}:done`, severity: "success", textKey: "job.done" });
  });

  it("a cancelled job is information", () => {
    const [entry] = run({ jobs: [mkJob(J1, "cancelled")], printers: [A] });
    expect(entry).toMatchObject({ id: `job:${J1}:cancelled`, severity: "info", textKey: "job.cancelled" });
  });

  it.each(["failed", "failed_restart"])("an unresolved %s job is an error with the error text of the job page", (state) => {
    const [entry] = run({ jobs: [mkJob(J1, state, { error: "Printer reported: cover open" })], printers: [A] });
    expect(entry).toMatchObject({
      id: `job:${J1}:${state}`,
      severity: "error",
      textKey: "job.failed",
      values: { error: "Printer reported: cover open" },
      target: { to: "/jobs/$jobId", params: { jobId: J1 } },
    });
    expect(entry?.resolved).toBeUndefined();
  });

  it("a failed job retried to done is resolved and info", () => {
    const failed = mkJob(J1, "failed", { error: "boom", updated_at: minutesAgo(20) });
    const retry = mkJob(J2, "done", { payload: { retry_of: J1 } });
    const entries = run({ jobs: [retry, failed], printers: [A] });
    expect(entries.find((e) => e.id === `job:${J1}:failed`)).toMatchObject({ severity: "info", resolved: true, textKey: "job.retried" });
    expect(entries.find((e) => e.id === `job:${J2}:done`)).toMatchObject({ severity: "success" });
  });

  it("a failed job whose retry is not done yet stays an error", () => {
    const failed = mkJob(J1, "failed", { updated_at: minutesAgo(20) });
    const retry = mkJob(J2, "printing", { payload: { retry_of: J1 } });
    expect(run({ jobs: [retry, failed], printers: [A] }).find((e) => e.id === `job:${J1}:failed`)).toMatchObject({ severity: "error" });
  });

  it("a chain failed → failed → done resolves both", () => {
    const first = mkJob(J1, "failed", { updated_at: minutesAgo(30) });
    const second = mkJob(J2, "failed", { updated_at: minutesAgo(20), payload: { retry_of: J1 } });
    const last = mkJob(J3, "done", { updated_at: minutesAgo(10), payload: { retry_of: J2 } });
    const entries = run({ jobs: [last, second, first], printers: [A] });
    expect(entries.find((e) => e.id === `job:${J1}:failed`)?.resolved).toBe(true);
    expect(entries.find((e) => e.id === `job:${J2}:failed`)?.resolved).toBe(true);
  });

  it("tolerates a retry_of that no longer resolves, is not a string or loops", () => {
    const gone = mkJob(J2, "done", { payload: { retry_of: "bbbbbbbb-0000-4000-8000-000000000009" } });
    const odd = mkJob(J3, "done", { payload: { retry_of: 7 } });
    const loop1 = mkJob("cccccccc-0000-4000-8000-000000000001", "done", { payload: { retry_of: "cccccccc-0000-4000-8000-000000000002" } });
    const loop2 = mkJob("cccccccc-0000-4000-8000-000000000002", "failed", { payload: { retry_of: "cccccccc-0000-4000-8000-000000000001" } });
    const entries = run({ jobs: [gone, odd, loop1, loop2], printers: [A] });
    expect(entries).toHaveLength(4);
  });

  it("a state change is a new entry id", () => {
    const queued = run({ jobs: [mkJob(J1, "queued")], printers: [A] })[0]!;
    const printing = run({ jobs: [mkJob(J1, "printing")], printers: [A] })[0]!;
    expect(queued.id).not.toBe(printing.id);
  });

  it("leaves out a job last changed more than a day ago", () => {
    expect(run({ jobs: [mkJob(J1, "failed", { updated_at: minutesAgo(24 * 60 + 1) })], printers: [A] })).toEqual([]);
  });

  it("names a page job by its page, and an unknown printer by an empty name", () => {
    const [entry] = run({ jobs: [mkJob(J1, "done", { template_key: null, payload: {} })], printers: [] });
    expect(entry?.values.printer).toBe("");
    expect(entry?.values.title).toBe("");
  });
});

describe("deriveNotifications: printers", () => {
  const one = (printer: Printer, st: PrinterStatus | undefined, jobs: Job[] = []) =>
    run({ printers: [printer], statuses: { [printer.id]: st }, jobs });

  it("an offline printer is an error that opens the printer page", () => {
    const [entry] = one(A, okStatus(A, { online: false, last_error: "no route" }));
    expect(entry).toMatchObject({
      id: `printer:${A.id}:offline`,
      severity: "error",
      kind: "printer",
      textKey: "printer.offline",
      values: { printer: A.name, detail: "no route" },
      target: { to: "/printers/$printerId", params: { printerId: A.id } },
    });
  });

  it("a printer with an error state is an error", () => {
    const [entry] = one(A, okStatus(A, { error_state: "cover open" }));
    expect(entry).toMatchObject({ id: `printer:${A.id}:error`, severity: "error", values: { detail: "cover open" } });
  });

  it("a stopped page printer with a blocking reason is an error and names the reasons", () => {
    const st = pageStatus(PAGE.id, { printer_state: "stopped", state_reasons: [{ keyword: "media-empty", severity: "error", blocking: true }] });
    const [entry] = one(PAGE, st);
    expect(entry).toMatchObject({ id: `printer:${PAGE.id}:stopped`, severity: "error", values: { reasons: "media-empty" } });
  });

  it("a stopped page printer without a serious reason is a warning", () => {
    const st = pageStatus(PAGE.id, { printer_state: "stopped", state_reasons: [{ keyword: "toner-low", severity: "warning", blocking: false }] });
    expect(one(PAGE, st)[0]).toMatchObject({ id: `printer:${PAGE.id}:stopped`, severity: "warning" });
  });

  it("a printer that answered as another device is an error (#231)", () => {
    const [entry] = one(A, okStatus(A, { identity_mismatch: true }));
    expect(entry).toMatchObject({ id: `printer:${A.id}:different_device`, severity: "error", textKey: "printer.different_device" });
  });

  it("a paused printer is a warning", () => {
    const [entry] = one({ ...A, paused: true }, okStatus(A));
    expect(entry).toMatchObject({ id: `printer:${A.id}:paused`, severity: "warning", textKey: "printer.paused" });
  });

  it("a stale status is a warning (#227)", () => {
    expect(one(A, okStatus(A, { stale: true }))[0]).toMatchObject({ id: `printer:${A.id}:stale`, severity: "warning" });
  });

  it("a printer nobody polls is a warning", () => {
    expect(one(A, okStatus(A, { polled: false }))[0]).toMatchObject({ id: `printer:${A.id}:not_polled`, severity: "warning" });
  });

  it("a low or empty supply is a warning in the status's own words", () => {
    const st = pageStatus(PAGE.id, {
      markers: [
        { name: "Black toner", color: "#000", level_percent: 3, low: true, empty: false, some_remaining: true, type: "toner" },
        { name: "Cyan ink", color: "#0ff", level_percent: 0, low: true, empty: true, some_remaining: false, type: "ink" },
        { name: "Waste", color: null, level_percent: 90, low: false, empty: false, some_remaining: true, type: "waste" },
      ],
    });
    const [entry] = one(PAGE, st);
    expect(entry).toMatchObject({
      id: `printer:${PAGE.id}:material`,
      severity: "warning",
      textKey: "printer.material",
      values: { printer: PAGE.name, empty: "Cyan ink", low: "Black toner" },
    });
  });

  it("a ready, a printing and a status-less printer make no entry", () => {
    expect(one(A, okStatus(A))).toEqual([]);
    expect(one(A, undefined)).toEqual([]);
    expect(one(A, okStatus(A), [mkJob(J1, "printing")]).filter((e) => e.kind === "printer")).toEqual([]);
  });

  it("printer entries take their time from firstSeen, else from now", () => {
    const seen = minutesAgo(90);
    const known = one(A, okStatus(A, { online: false }));
    expect(known[0]?.at).toBe(new Date(NOW).toISOString());
    const [entry] = run({ printers: [A], statuses: { [A.id]: okStatus(A, { online: false }) }, firstSeen: { [`printer:${A.id}:offline`]: seen } });
    expect(entry?.at).toBe(seen);
  });
});

describe("deriveNotifications: sheets", () => {
  it("a sheet with unconfirmed cells is a warning that opens the sheet", () => {
    const [entry] = run({ sheets: [sheet("AB-12", 3)] });
    expect(entry).toMatchObject({
      id: "sheet:AB-12:unconfirmed",
      severity: "warning",
      kind: "sheet",
      textKey: "sheet.unconfirmed",
      values: { count: "3", code: "AB-12" },
      target: { to: "/sheets/$code", params: { code: "AB-12" } },
    });
  });

  it("a sheet without unconfirmed cells and a discarded sheet make no entry", () => {
    expect(run({ sheets: [sheet("AB-12", 0), { ...sheet("AB-13", 2), state: "discarded" }] })).toEqual([]);
  });

  it("sheet entries take their time from firstSeen", () => {
    const seen = minutesAgo(10);
    expect(run({ sheets: [sheet("AB-12", 1)], firstSeen: { "sheet:AB-12:unconfirmed": seen } })[0]?.at).toBe(seen);
  });
});

describe("deriveNotifications: the list", () => {
  it("is newest first", () => {
    const entries = run({
      printers: [A],
      jobs: [mkJob(J1, "done", { updated_at: minutesAgo(50) }), mkJob(J2, "done", { updated_at: minutesAgo(5) }), mkJob(J3, "done", { updated_at: minutesAgo(20) })],
    });
    expect(entries.map((e) => e.id)).toEqual([`job:${J2}:done`, `job:${J3}:done`, `job:${J1}:done`]);
  });

  it("holds at most 100 entries, the newest", () => {
    const jobs = Array.from({ length: 130 }, (_, i) => mkJob(`dddddddd-0000-4000-8000-${String(i).padStart(12, "0")}`, "done", { updated_at: new Date(NOW - (i + 1) * 1000).toISOString() }));
    const entries = run({ jobs, printers: [A] });
    expect(entries).toHaveLength(100);
    expect(entries[0]?.id).toBe(`job:${jobs[0]!.id}:done`);
    expect(entries[99]?.id).toBe(`job:${jobs[99]!.id}:done`);
  });

  describe("a standing condition survives a busy install", () => {
    const busy = Array.from({ length: 101 }, (_, i) => mkJob(`eeeeeeee-0000-4000-8000-${String(i).padStart(12, "0")}`, "done", { updated_at: new Date(NOW - (i + 1) * 1000).toISOString() }));
    const offlineSince = new Date(NOW - 5 * 3_600_000).toISOString();
    const base = { jobs: busy, printers: [A], statuses: { [A.id]: okStatus(A, { online: false }) }, firstSeen: { [`printer:${A.id}:offline`]: offlineSince } };

    it("an offline printer survives 101 newer done jobs", () => {
      const entries = run(base);
      expect(entries).toHaveLength(100);
      expect(entries.map((e) => e.id)).toContain(`printer:${A.id}:offline`);
    });

    it("a sheet warning and an unresolved failed job survive too, and the rest is capped", () => {
      const failed = mkJob(J1, "failed", { updated_at: minutesAgo(600), error: "x" });
      const entries = run({ ...base, jobs: [...busy, failed], sheets: [sheet("S1", 2)] });
      const ids = entries.map((e) => e.id);
      expect(ids).toContain(`printer:${A.id}:offline`);
      expect(ids).toContain("sheet:S1:unconfirmed");
      expect(ids).toContain(`job:${J1}:failed`);
      expect(entries).toHaveLength(100);
    });

    it("the time of the printer entry stays across a re-derive", () => {
      const first = run(base).find((e) => e.id === `printer:${A.id}:offline`);
      const again = deriveNotifications({ sheets: [], ...base, now: NOW + 60_000 }).find((e) => e.id === `printer:${A.id}:offline`);
      expect(first?.at).toBe(offlineSince);
      expect(again?.at).toBe(offlineSince);
    });
  });

  it("is stable for entries of the same time", () => {
    const same = minutesAgo(5);
    const a = run({ printers: [A], jobs: [mkJob(J1, "done", { updated_at: same }), mkJob(J2, "done", { updated_at: same })] });
    const b = run({ printers: [A], jobs: [mkJob(J2, "done", { updated_at: same }), mkJob(J1, "done", { updated_at: same })] });
    expect(a.map((e) => e.id)).toEqual(b.map((e) => e.id));
  });

  it("makes no entry for printer B when only A is listed (unknown printer ids are not invented)", () => {
    expect(run({ printers: [A], statuses: { [B.id]: okStatus(B, { online: false }) } })).toEqual([]);
  });
});
