// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { i18n } from "@lingui/core";
import { beforeEach, describe, expect, it } from "vitest";
import { initI18n } from "../../i18n";
import { printErrorText, type Translate } from "./printErrorText";

const t: Translate = (d) => i18n._(d);
const UNREACHABLE = "The printer is not reachable. Check that it is switched on and connected, then try again.";

describe("printErrorText", () => {
  beforeEach(async () => {
    await initI18n("en");
  });

  it.each([
    ["unsupported_tape", null, "This tape width cannot print this label. Load another tape."],
    ["unsupported_tape", { tape_mm: 70 }, "This label cannot print on 70 mm tape. Load another tape."],
    ["printer_cover_open", null, "The printer cover is open. Close it and try again."],
    ["no_tape_loaded", null, "No tape is loaded. Put in a tape and try again."],
    ["tape_empty", null, "The tape is empty. Put in a new tape and try again."],
    ["tape_mismatch", { expected_mm: 12, loaded_mm: 24 }, "The loaded tape (24 mm) does not match this label (12 mm)."],
    ["tape_mismatch", { expected_mm: 12, loaded_mm: null }, "The loaded tape does not match this label."],
    ["content_type_data_mismatch", { missing_fields: ["title"] }, "The label is missing data this layout needs."],
    ["printer_offline", null, UNREACHABLE],
    ["snmp_query_failed", null, UNREACHABLE],
  ] as const)("%s %j reads in the app's own words", (code, detail, words) => {
    expect(printErrorText(code, detail, t)).toBe(words);
  });

  it("keeps the QR, spool-only and orientation texts", () => {
    expect(printErrorText("qr_payload_too_long", { length: 300, max_bytes: 100 }, t)).toBe(
      "The link in the QR code is 300 bytes long, but this layout holds at most 100 bytes. Pick another arrangement or a shorter link.",
    );
    expect(printErrorText("qr_payload_too_long", null, t)).toBe("The link in the QR code is too long for this layout.");
    expect(printErrorText("unsupported_tape", { tape_mm: 29, content_types: ["qr_one_line"] }, t)).toBe(
      "Only the spool label prints on 29 mm tape. Remove the other labels from the cart or load 62 mm tape.",
    );
    expect(printErrorText("conflicting_orientation", null, t)).toBe(
      "These labels ask for different directions (along and across). Print them in separate runs.",
    );
  });

  it("kebab and snake codes give the same text", () => {
    for (const [snake, kebab] of [
      ["printer_cover_open", "printer-cover-open"],
      ["unsupported_tape", "unsupported-tape"],
      ["content_type_data_mismatch", "content-type-data-mismatch"],
      ["tape_empty", "https://labelyard.example.invalid/problems/tape-empty"],
    ] as const) {
      expect(printErrorText(kebab, { tape_mm: 70 }, t)).toBe(printErrorText(snake, { tape_mm: 70 }, t));
      expect(printErrorText(kebab, { tape_mm: 70 }, t)).not.toBeNull();
    }
  });

  it("de: the cover sentence is German", async () => {
    await initI18n("de");
    expect(printErrorText("printer-cover-open", null, t)).toBe("Der Deckel des Druckers ist offen. Schließe ihn und versuche es erneut.");
    expect(printErrorText("unsupported_tape", { tape_mm: 70 }, t)).toBe(
      "Dieses Etikett lässt sich nicht auf 70-mm-Band drucken. Lege ein anderes Band ein.",
    );
  });

  it("an unknown code gives null", () => {
    expect(printErrorText("something_new", null, t)).toBeNull();
    expect(printErrorText(null, null, t)).toBeNull();
    expect(printErrorText(undefined, null, t)).toBeNull();
  });
});
