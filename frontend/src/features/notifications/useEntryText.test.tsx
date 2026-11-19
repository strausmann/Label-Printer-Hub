// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { i18n } from "@lingui/core";
import { I18nProvider } from "@lingui/react";
import { renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { initI18n } from "../../i18n";
import { useEntryText } from "./useEntryText";

async function failedText(values: Record<string, string>, lang: "en" | "de") {
  await initI18n(lang);
  const { result } = renderHook(() => useEntryText(), {
    wrapper: ({ children }) => <I18nProvider i18n={i18n}>{children}</I18nProvider>,
  });
  return result.current({ textKey: "job.failed", values: { title: "Box", printer: "QL", ...values } });
}

describe("a failed job's entry (#389)", () => {
  it("says a stored error code in the app's words, with the flags the printer reported", async () => {
    const values = { error: "printer_error: The printer reports an error: jammed", errorDetail: JSON.stringify({ flags: ["jammed"] }) };
    expect(await failedText(values, "en")).toBe("Box failed: The printer reports: Tape jammed — clear it to print. Fix it on the printer and retry.");
    const de = await failedText(values, "de");
    expect(de).not.toMatch(/The printer|jammed/);
  });

  it("an error without a known code keeps the stored text", async () => {
    expect(await failedText({ error: "Printer reported: cover open" }, "en")).toBe("Box failed: Printer reported: cover open");
    expect(await failedText({ error: "weird_code: something odd" }, "en")).toBe("Box failed: weird_code: something odd");
  });
});
