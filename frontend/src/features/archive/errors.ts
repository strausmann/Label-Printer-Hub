// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useLingui } from "@lingui/react/macro";
import { ApiError } from "../../api/client";
import { invalidGeometry, labelTooLong, prefixTaken, typeInUse } from "../../api/errorDetail";

/** The server's names for the fields it complains about, as words. */
function useFieldWords(): (field: string) => string {
  const { t } = useLingui();
  return (field) => {
    const words: Record<string, string> = {
      cols: t`The number of columns`,
      rows: t`The number of rows`,
      label_w: t`The label width`,
      label_h: t`The label height`,
      pitch_x: t`The horizontal pitch`,
      pitch_y: t`The vertical pitch`,
      margin_top: t`The top margin`,
      margin_left: t`The left margin`,
      corner_radius: t`The corner radius`,
      page_size: t`The paper size`,
      page_w: t`The page width`,
      page_h: t`The page height`,
      shape: t`The label shape`,
      key: t`The key`,
      prefix: t`The code prefix`,
      vendor: t`The vendor`,
      description: t`The description`,
      product_codes: t`The list of product codes`,
      source_name: t`The source name`,
      source_url: t`The source address`,
      notes: t`The notes text`,
      change_note: t`The note about the change`,
    };
    return words[field] ?? field;
  };
}

/**
 * The sentence for a `422 invalid_geometry`. The server's reasons are English phrases
 * (`backend/app/sheets/geometry.py`, `type_service.py`); each known one has its own message, and
 * an unknown one gets a generic sentence with the keyword only as a trailing detail.
 */
function useGeometrySentence(): (field: string, reason: string) => string {
  const { t } = useLingui();
  const word = useFieldWords();
  return (field, reason) => {
    const what = word(field);
    if (reason.startsWith("cols x rows must not exceed")) return t`The grid has too many labels: at most 400 per sheet.`;
    switch (reason) {
      case "not a finite number":
      case "not a valid number":
        return t`${what} is not a valid number.`;
      case "must not be negative":
        return t`${what} must not be negative.`;
      case "at most two decimals allowed":
        return t`${what} can have at most two decimals.`;
      case "must be greater than zero":
        return t`${what} must be greater than zero.`;
      case "must be at least 1":
        return t`${what} must be at least 1.`;
      case "must be A4 or Letter":
      case "does not match the page size":
        return t`The page size is not valid.`;
      case "must be rectangle or round":
        return t`The label shape must be rectangle or round.`;
      case "must not be smaller than label_w":
        return t`The horizontal pitch must not be smaller than the label width.`;
      case "must not be smaller than label_h":
        return t`The vertical pitch must not be smaller than the label height.`;
      case "round labels need label_w equal to label_h":
        return t`Round labels must be as high as they are wide.`;
      case "grid is wider than the page":
        return t`The grid does not fit on the page: it is wider than the page.`;
      case "grid is taller than the page":
        return t`The grid does not fit on the page: it is taller than the page.`;
      case "unchanged":
        return t`The measurements are the same as in the current version. Change something first.`;
      case "too long":
        return t`${what} is too long.`;
      case "too many":
        return t`${what} has too many entries.`;
      case "invalid format":
        return t`${what} has the wrong format.`;
      case "must not be empty":
        return t`${what} must not be empty.`;
    }
    return t`The server did not accept this value. ${what} (${reason}).`;
  };
}

/** The scope a `403 insufficient_scope` names (the server's text is "Key has scope 'x' but 'y' is required"); null when it names none we know. */
function requiredScope(error: ApiError): "read" | "print" | "admin" | null {
  const match = /but '(read|print|admin)' is required/.exec(error.detail);
  return match ? (match[1] as "read" | "print" | "admin") : null;
}

/** The words for a failed archive request: the server's code first, its own text only as a last resort. */
export function useArchiveErrorText(): (error: unknown, fallback?: string) => string {
  const { t } = useLingui();
  const geometrySentence = useGeometrySentence();
  return (error, fallback) => {
    if (error instanceof ApiError) {
      const geometry = invalidGeometry(error);
      if (geometry) return geometrySentence(geometry.field, geometry.reason);
      const tooLong = labelTooLong(error);
      if (tooLong) return geometrySentence(tooLong.field, "too long");
      if (error.code === "label_too_long") return t`A text is too long.`;
      const prefix = prefixTaken(error);
      if (prefix) {
        return prefix.reason === "sheets_exist"
          ? t`The code prefix cannot change while sheets of this type exist.`
          : t`Another type already uses this code prefix.`;
      }
      const inUse = typeInUse(error);
      if (inUse) {
        return inUse.reason === "has_sheets"
          ? t`This type has sheets. Archive it instead.`
          : t`Only your own types can be deleted. Archive this one instead.`;
      }
      switch (error.code) {
        case "network_error":
          return t`The server cannot be reached.`;
        case "type_exists":
          return t`A sheet type with this key already exists.`;
        case "sheet_type_archived":
          return t`This type is archived. Bring it back first.`;
        case "sheet_type_not_found":
          return t`That sheet type does not exist.`;
        case "scope_too_low":
          return t`You need an admin key for this.`;
        case "insufficient_scope": {
          const scope = requiredScope(error);
          if (scope === "admin") return t`You need an admin key for this.`;
          if (scope === "print") return t`Printing and marking cells need a print or admin key.`;
          return t`This key may not do this.`;
        }
        case "printer_not_allowed":
          return t`This key may not use this printer.`;
        case "invalid_placements":
          return t`The split of this print no longer fits. Check the preview and try again.`;
        case "insufficient_cells":
          return t`The sheet has no free cell left for this.`;
        case "sheet_type_mismatch":
          return t`That sheet is of another type than this print needs.`;
        case "media_kind_mismatch":
          return t`That printer cannot print sheets.`;
      }
      if (error.status === 403) return t`This key may not do this.`;
      // An unknown code gets no echo of the server's English sentence: a localized line with the code to look up.
      if (error.code && error.status !== 0) {
        const code = error.code;
        return t`The server did not accept this (${code}).`;
      }
    }
    return fallback ?? t`Saving failed.`;
  };
}
