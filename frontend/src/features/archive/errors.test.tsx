import { I18nProvider } from "@lingui/react";
import { renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it } from "vitest";
import { ApiError } from "../../api/client";
import { i18n, initI18n } from "../../i18n";
import { useArchiveErrorText } from "./errors";

const wrapper = ({ children }: { children: ReactNode }) => <I18nProvider i18n={i18n}>{children}</I18nProvider>;
const words = (error: unknown, fallback?: string) => renderHook(() => useArchiveErrorText(), { wrapper }).result.current(error, fallback);
const api = (status: number, code: string | null, detail = "text", errorDetail: Record<string, unknown> | null = null) =>
  new ApiError(status, code, detail, errorDetail);

beforeEach(async () => {
  await initI18n("en");
});

describe("useArchiveErrorText", () => {
  it.each([
    [api(0, "network_error"), "The server cannot be reached."],
    [api(409, "type_exists"), "A sheet type with this key already exists."],
    [api(409, "sheet_type_archived"), "This type is archived. Bring it back first."],
    [api(404, "sheet_type_not_found"), "That sheet type does not exist."],
    [api(403, "scope_too_low"), "You need an admin key for this."],
    [api(403, null, "HTTP 403"), "This key may not do this."],
    [api(403, "insufficient_scope", "Key has scope 'read' but 'admin' is required"), "You need an admin key for this."],
    [api(403, "insufficient_scope", "Key has scope 'read' but 'print' is required"), "Printing and marking cells need a print or admin key."],
    [api(403, "insufficient_scope", "something else"), "This key may not do this."],
    [api(403, "printer_not_allowed", "x"), "This key may not use this printer."],
    [api(422, "invalid_placements", "The placements are not valid.", { reason: "count_mismatch" }), "The split of this print no longer fits. Check the preview and try again."],
    [api(422, "some_new_code", "A sentence in English"), "The server did not accept this (some_new_code)."],
    [api(409, "type_in_use", "x", { reason: "has_sheets" }), "This type has sheets. Archive it instead."],
    [api(409, "type_in_use", "x", { reason: "seed_type" }), "Only your own types can be deleted. Archive this one instead."],
    [api(409, "prefix_taken", "x", { reason: "sheets_exist" }), "The code prefix cannot change while sheets of this type exist."],
    [api(409, "prefix_taken", "x", { reason: "prefix_in_use" }), "Another type already uses this code prefix."],
  ])("%#: reads the server's code", (error, sentence) => {
    expect(words(error)).toBe(sentence);
  });

  it("falls back to the caller's sentence or a generic one when the error says nothing", () => {
    expect(words(api(500, null, "HTTP 500"))).toBe("Saving failed.");
    expect(words(api(500, null, "The database is busy"))).toBe("Saving failed.");
    expect(words(api(500, null, "HTTP 500"), "The import failed.")).toBe("The import failed.");
    expect(words(new Error("plain"))).toBe("Saving failed.");
  });

  it.each([
    ["cols", "cols x rows must not exceed 400", "The grid has too many labels: at most 400 per sheet."],
    ["label_w", "must be greater than zero", "The label width must be greater than zero."],
    ["margin_top", "at most two decimals allowed", "The top margin can have at most two decimals."],
    ["page_w", "does not match the page size", "The page size is not valid."],
    ["label_h", "round labels need label_w equal to label_h", "Round labels must be as high as they are wide."],
    ["rows", "grid is taller than the page", "The grid does not fit on the page: it is taller than the page."],
    ["notes", "too long", "The notes text is too long."],
    ["product_codes", "too many", "The list of product codes has too many entries."],
    ["prefix", "invalid format", "The code prefix has the wrong format."],
    ["change_note", "must not be empty", "The note about the change must not be empty."],
    ["no_such_field", "no such reason", "The server did not accept this value. no_such_field (no such reason)."],
  ])("invalid_geometry on %s: %s", (field, reason, sentence) => {
    expect(words(api(422, "invalid_geometry", "x", { field, reason }))).toBe(sentence);
  });
});
