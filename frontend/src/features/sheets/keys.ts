// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import type { components } from "../../api/schema.gen";

export type SheetPrintRequest = components["schemas"]["SheetPrintRequest"];

/*
 * Query keys of the sheet screens. The event hook (api/events.ts) invalidates them, so they live
 * in a module with no other imports. Previews sit OUTSIDE `["printers", …]` on purpose: every
 * `printer.status` event invalidates that tree, and a worst-case preview costs 7–10 s to render.
 * Capabilities and calibration sit INSIDE it, so a printer event refreshes them.
 */
export const sheetsListKey = ["sheets", "list"] as const;
export const sheetsKey = (filters: object = {}) => ["sheets", "list", filters] as const;
export const sheetKey = (code: string) => ["sheets", "detail", code] as const;
export const nextCodeKey = (typeKey: string) => ["sheets", "next-code", typeKey] as const;
export const marginCheckKey = (typeKey: string, printer: string, tray: string | null) =>
  ["sheets", "margin-check", typeKey, printer, tray] as const;

export const typesListKey = ["sheet-types", "list"] as const;
export const typesKey = (filters: object = {}) => ["sheet-types", "list", filters] as const;
export const typeKey = (key: string) => ["sheet-types", "detail", key] as const;

export const calibrationKey = (printerId: string) => ["printers", printerId, "calibration"] as const;
export const capabilitiesKey = (printerId: string) => ["printers", printerId, "capabilities"] as const;

export const SHEET_PREVIEW_KEY = "sheet-preview";
export const sheetPreviewKey = (printerId: string, request: SheetPrintRequest) =>
  [SHEET_PREVIEW_KEY, printerId, request] as const;

/** True when the request behind a preview key places onto, or expects cells of, this sheet. */
export function previewNamesCode(queryKey: readonly unknown[], code: string): boolean {
  const request = queryKey[2] as Partial<SheetPrintRequest> | undefined;
  if (!request || typeof request !== "object") return false;
  return (
    (request.placements ?? []).some((p) => p.sheet === code) || (request.expected_cells ?? []).some((e) => e.sheet === code)
  );
}
