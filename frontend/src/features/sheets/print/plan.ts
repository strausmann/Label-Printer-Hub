import type { CartItem } from "../../lookup/cart";
import type { SheetSummary } from "../api";
import type { SheetPrintRequest } from "../keys";

/** The server's limit of one sheet print request (`SheetPrintRequest`). One run prints one sheet (#277). */
export const MAX_ITEMS = 500;

export type PlacementIn = SheetPrintRequest["placements"][number];
export type SheetItem = SheetPrintRequest["items"][number];

/** Where the labels go: a sheet that exists, or a new one of the chosen type. */
export type Target = { kind: "sheet"; code: string } | { kind: "new" };

export interface Fill {
  /** `first_free` takes the free cells in order; `choose` takes exactly the cells picked by hand. */
  mode: "first_free" | "choose";
  chosen: readonly number[];
  /** Free cells `first_free` leaves out (for example a damaged label). Never stored. */
  skipped: readonly number[];
}

export type Verdict =
  | { kind: "ok" }
  | { kind: "unknown" }
  | { kind: "discarded" }
  | { kind: "full" }
  | { kind: "other_type"; typeKey: string };

export const countItems = (lines: readonly CartItem[]): number => lines.reduce((sum, l) => sum + l.copies, 0);

/** A sheet item has no copies: every copy of a cart line is an item of its own (C20). */
export function expandItems(lines: readonly CartItem[]): SheetItem[] {
  return lines.flatMap((line) =>
    Array.from({ length: line.copies }, () => ({
      content_type: line.content_type,
      lookup: { app: line.app, identifier: line.id },
    })),
  );
}

/** Free cells as the server counts them: reserved and unconfirmed cells are not free either (N17). */
export const freeOf = (s: Pick<SheetSummary, "total" | "used" | "reserved" | "unconfirmed">): number =>
  Math.max(0, s.total - s.used - s.reserved - s.unconfirmed);

/** The placement for one target. `choose` cells and `skip` never go together; a new sheet prints its ID in the margin (the server's default, which takes no cell). */
export function placementFor(target: Target, typeKey: string, fill: Fill, count?: number): PlacementIn {
  const withCount = count === undefined ? {} : { count };
  if (target.kind === "new") return { new_sheet: { type: typeKey, id_placement: "margin" }, cells: "first_free", ...withCount };
  if (fill.mode === "choose") return { sheet: target.code, cells: [...fill.chosen].sort((a, b) => a - b), ...withCount };
  return {
    sheet: target.code,
    cells: "first_free",
    ...(fill.skipped.length > 0 ? { skip: [...fill.skipped] } : {}),
    ...withCount,
  };
}

/** Whether a sheet can take labels of `typeKey`; `null` is a code the hub does not know. */
export function judgeSheet(sheet: Pick<SheetSummary, "state" | "type_key" | "total" | "used" | "reserved" | "unconfirmed"> | null, typeKey: string): Verdict {
  if (!sheet) return { kind: "unknown" };
  if (sheet.state === "discarded") return { kind: "discarded" };
  if (sheet.type_key !== typeKey) return { kind: "other_type", typeKey: sheet.type_key };
  if (freeOf(sheet) === 0) return { kind: "full" };
  return { kind: "ok" };
}

/** Sheets that hold all `needed` labels first (the tightest fit first, so a nearly full sheet is used up), then the rest by room. */
export function fittingFirst<T extends SheetSummary>(sheets: readonly T[], needed: number): Array<{ sheet: T; fits: boolean }> {
  const tagged = sheets.map((sheet) => ({ sheet, fits: freeOf(sheet) >= needed }));
  const fits = tagged.filter((s) => s.fits).sort((a, b) => freeOf(a.sheet) - freeOf(b.sheet));
  const rest = tagged.filter((s) => !s.fits).sort((a, b) => freeOf(b.sheet) - freeOf(a.sheet));
  return [...fits, ...rest];
}
