// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApiError } from "../../api/client";
import { initI18n } from "../../i18n";
import { I18nProvider } from "@lingui/react";
import { i18n } from "@lingui/core";
import { useSheetErrorText } from "./errors";

async function textFor(error: unknown, fallback?: string) {
  await initI18n("en");
  const { result } = renderHook(() => useSheetErrorText(), { wrapper: ({ children }) => <I18nProvider i18n={i18n}>{children}</I18nProvider> });
  return result.current(error, fallback);
}
const api = (code: string, status = 409) => new ApiError(status, code, "server words");

describe("sheet error words", () => {
  it.each([
    ["sheet_busy", "A running job still uses this sheet. Try again when it has finished."],
    ["sheet_not_found", "That sheet does not exist."],
    ["sheet_discarded", "This sheet is discarded."],
    ["printer_not_found", "That printer does not exist."],
    ["printer_disabled", "This printer is switched off."],
    ["printer-unavailable", "The print queue does not know this printer yet. Try again in a moment."],
    ["tray_unknown", "The printer does not report that tray."],
    ["cell_out_of_range", "A marked cell is outside the sheet."],
    ["ipp_unreachable", "The printer could not be reached."],
    ["ipp_rejected", "The printer did not accept the ID label."],
    ["ipp_bad_response", "The printer did not accept the ID label."],
    // The held refusal arrives as the sheet envelope (print) and as a problem type (calibration page).
    ["printer-identity-mismatch", "This printer may be a different device now. An admin has to confirm it on the printer's page first."],
  ])("%s", async (code, words) => {
    expect(await textFor(api(code))).toBe(words);
  });

  it("hands what it does not know to the archive's table, and then to the fallback", async () => {
    expect(await textFor(api("sheet_type_archived"))).toBe("This type is archived. Bring it back first.");
    expect(await textFor(new ApiError(500, null, "HTTP 500"), "The sheet could not be added.")).toBe("The sheet could not be added.");
    expect(await textFor(new Error("boom"), "Nope")).toBe("Nope");
  });
});

describe("cell write errors", () => {
  it.each([
    ["cells_taken", "One of those cells is already in use. The sheet shows the current state."],
    ["cells_not_marked_by_hand", "Only cells that were marked by hand can be un-marked."],
    ["cells_not_unconfirmed", "Those cells are no longer waiting for confirmation."],
  ])("%s", async (code, words) => {
    expect(await textFor(api(code))).toBe(words);
  });
});
