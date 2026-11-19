// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { beforeEach, describe, expect, it } from "vitest";
import { i18n, initI18n } from "../../i18n";
import { job, PRINTER_A, PRINTER_B } from "../test-api";
import type { Job } from "./api";
import { flagSeverity, flagText, NOT_WAITING, printerWaiting, type Waiting } from "./flags";

const FLAGS = [
  "lowPaper",
  "noPaper",
  "lowToner",
  "noToner",
  "doorOpen",
  "jammed",
  "offline",
  "serviceRequested",
  "inputTrayMissing",
  "outputTrayMissing",
  "markerSupplyMissing",
  "outputFull",
  "inputTrayEmpty",
  "overduePreventMaint",
];

const t = () => i18n._.bind(i18n);
const J1 = "aaaaaaaa-0000-4000-8000-000000000001";
const J2 = "aaaaaaaa-0000-4000-8000-000000000002";
const mk = (id: string, state: string, over: Record<string, unknown> = {}, printer = PRINTER_A.id): Job =>
  job(id, printer, state, over) as unknown as Job;
const titled = (title: string) => ({ payload: { label_data: { title } } });

describe("flagText", () => {
  beforeEach(async () => {
    await initI18n("en");
  });

  it("every RFC 3805 flag has words", () => {
    for (const flag of FLAGS) {
      const text = flagText(flag, t());
      expect(text.detail, flag).toBeNull();
      expect(text.headline, flag).not.toBe(flag);
      expect(text.headline, flag).not.toBe("The printer reports a problem.");
    }
  });

  it("the cover sentence in English and German", async () => {
    expect(flagText("doorOpen", t()).headline).toBe("Cover open — close it to print");
    await initI18n("de");
    expect(flagText("doorOpen", t()).headline).toBe("Deckel offen – zum Drucken schließen");
  });

  it("an unknown flag is a generic problem with the flag in the detail", () => {
    expect(flagText("developerLow", t())).toEqual({ headline: "The printer reports a problem.", detail: "developerLow" });
    expect(flagText("constructor", t()).detail).toBe("constructor");
  });
});

describe("printerWaiting", () => {
  it("a queued job waits and is named", () => {
    expect(printerWaiting(PRINTER_A.id, [mk(J1, "queued", titled("Shelf 3"))], {})).toEqual({ waiting: true, job: "Shelf 3", refused: false });
  });

  it("a printing job waits", () => {
    expect(printerWaiting(PRINTER_A.id, [mk(J1, "printing", titled("Shelf 3"))], {}).waiting).toBe(true);
  });

  it("the oldest of two queued jobs is named", () => {
    const jobs = [
      mk(J1, "queued", { ...titled("Newer"), created_at: "2026-11-14T11:00:00Z" }),
      mk(J2, "queued", { ...titled("Older"), created_at: "2026-11-14T10:00:00Z" }),
    ];
    expect(printerWaiting(PRINTER_A.id, jobs, {}).job).toBe("Older");
  });

  it("a recorded refusal waits without a job", () => {
    expect(printerWaiting(PRINTER_A.id, [], { [PRINTER_A.id]: { title: "" } })).toEqual({ waiting: true, job: "", refused: true });
  });

  it("a done job does not wait", () => {
    expect(printerWaiting(PRINTER_A.id, [mk(J1, "done"), mk(J2, "failed")], {})).toEqual(NOT_WAITING);
  });

  it("a job or a refusal of another printer does not wait", () => {
    expect(printerWaiting(PRINTER_A.id, [mk(J1, "queued", {}, PRINTER_B.id)], { [PRINTER_B.id]: { title: "" } })).toEqual(NOT_WAITING);
  });
});

describe("flagSeverity", () => {
  const waiting: Waiting = { waiting: true, job: "Shelf 3", refused: false };

  it("cover open alone is a warning", () => {
    expect(flagSeverity("doorOpen", NOT_WAITING)).toBe("warning");
  });

  it("cover open while waiting is an error", () => {
    expect(flagSeverity("doorOpen", waiting)).toBe("error");
  });

  it("no paper is an error either way", () => {
    expect(flagSeverity("noPaper", NOT_WAITING)).toBe("error");
    expect(flagSeverity("noPaper", waiting)).toBe("error");
  });

  it("low paper is a warning", () => {
    expect(flagSeverity("lowPaper", NOT_WAITING)).toBe("warning");
    expect(flagSeverity("lowPaper", waiting)).toBe("warning");
  });

  it("an unknown flag is an error", () => {
    expect(flagSeverity("developerLow", NOT_WAITING)).toBe("error");
  });
});
