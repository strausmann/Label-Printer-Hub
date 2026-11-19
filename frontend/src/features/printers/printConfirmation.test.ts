// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { i18n } from "@lingui/core";
import { beforeEach, describe, expect, it } from "vitest";
import { initI18n } from "../../i18n";
import { printConfirmationText } from "./printConfirmation";
import type { Translate } from "./printErrorText";

const t: Translate = (d) => i18n._(d);
const record = (channel: "ipp" | "label_counter" | "none") => ({
  channel,
  confirm_transport: channel === "ipp" ? ("ipp" as const) : ("raw" as const),
  label_counter: channel !== "none",
  counter_read: true,
  ipp_incomplete: false,
  confirmed_at: "2026-11-18T09:00:00Z",
});
// R26-1: the test print found the counter, but the printer stopped answering it.
const counterOff = { ...record("none"), label_counter: true, counter_read: false };

describe("printConfirmationText (#393)", () => {
  beforeEach(async () => {
    await initI18n("en");
  });

  it.each([
    ["ipp", "Printer reports the job state (IPP)"],
    ["label_counter", "Label counter"],
    ["none", "Not confirmed"],
  ] as const)("names the %s channel", (channel, text) => {
    expect(printConfirmationText(record(channel), t)).toBe(text);
  });

  it("says when the label counter is not read at the moment (R26-1)", () => {
    expect(printConfirmationText(counterOff, t)).toBe("Not confirmed — the label counter does not answer; a test print checks again");
  });

  it("says why IPP is not tried when an earlier test print's IPP job did not finish", () => {
    expect(printConfirmationText({ ...record("label_counter"), ipp_incomplete: true }, t)).toBe(
      "Label counter — IPP is not tried: the printer did not finish a test print's IPP job",
    );
  });

  it("says both when the counter does not answer and IPP is not tried (R3-7)", () => {
    expect(printConfirmationText({ ...counterOff, ipp_incomplete: true }, t)).toBe(
      "Not confirmed — the label counter does not answer, and IPP is not tried: the printer did not finish a test print's IPP job",
    );
  });

  it("says a printer without a record has not been tested yet", () => {
    expect(printConfirmationText(null, t)).toBe("Not tested yet — a test print finds out");
    expect(printConfirmationText(undefined, t)).toBe("Not tested yet — a test print finds out");
  });
});

describe("printConfirmationText in German (#393)", () => {
  beforeEach(async () => {
    await initI18n("de");
  });

  it("speaks German", () => {
    expect(printConfirmationText(record("label_counter"), t)).toBe("Etikettenzähler");
    expect(printConfirmationText(record("ipp"), t)).toBe("Drucker meldet den Auftragsstatus (IPP)");
    expect(printConfirmationText(counterOff, t)).toBe("Nicht bestätigt – der Etikettenzähler antwortet nicht; ein Testdruck prüft es erneut");
    expect(printConfirmationText({ ...counterOff, ipp_incomplete: true }, t)).toBe(
      "Nicht bestätigt – der Etikettenzähler antwortet nicht, und IPP wird nicht versucht: Der Drucker hat den IPP-Auftrag eines Testdrucks nicht fertig gedruckt",
    );
    expect(printConfirmationText({ ...record("none"), ipp_incomplete: true }, t)).toBe(
      "Nicht bestätigt – IPP wird nicht versucht: Der Drucker hat den IPP-Auftrag eines Testdrucks nicht fertig gedruckt",
    );
  });
});
