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
  });
});
