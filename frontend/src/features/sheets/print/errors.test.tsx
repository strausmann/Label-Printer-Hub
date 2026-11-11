import { i18n } from "@lingui/core";
import { I18nProvider } from "@lingui/react";
import { renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApiError } from "../../../api/client";
import { initI18n } from "../../../i18n";
import { usePrintDialogErrorText } from "./errors";

async function textFor(error: unknown, lang: "en" | "de" = "en") {
  await initI18n(lang);
  const { result } = renderHook(() => usePrintDialogErrorText((i) => `Item ${i + 1}`), {
    wrapper: ({ children }) => <I18nProvider i18n={i18n}>{children}</I18nProvider>,
  });
  return result.current(error);
}

describe("print dialog error words", () => {
  it("a printer held after a device swap says an admin has to confirm it (sheet envelope)", async () => {
    const error = new ApiError(409, "printer-identity-mismatch", "server words", { printer_id: "p1" });
    expect(await textFor(error)).toBe(
      "This printer may be a different device now. An admin has to confirm it on the printer's page first.",
    );
  });

  it("a preview past the hub's render time limit says to try again later (#293), en and de", async () => {
    const error = new ApiError(504, "render-timeout", "server words");
    expect(await textFor(error)).toBe("The preview took too long. Try again later.");
    expect(await textFor(error, "de")).toBe("Die Vorschau hat zu lange gedauert. Versuch es später noch einmal.");
  });

  it("a preview without a free render slot says to try again later (#293), en and de", async () => {
    const error = new ApiError(503, "render-unavailable", "server words");
    expect(await textFor(error)).toBe("The hub cannot draw a preview right now. Try again later.");
    expect(await textFor(error, "de")).toBe(
      "Der Hub kann gerade keine Vorschau zeichnen. Versuch es später noch einmal.",
    );
  });

  it("an unknown error ends in the fallback, never in the server's words", async () => {
    expect(await textFor(new ApiError(500, null, "HTTP 500"))).toBe("The labels could not be put on the sheet.");
  });
});
