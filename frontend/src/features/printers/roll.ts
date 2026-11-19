// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useLingui } from "@lingui/react/macro";
import type { PrinterStatus } from "./api";

/** A roll in the printer that the hub cannot print on yet (#391: die-cut labels come in 1.8.0). */
export interface UnsupportedRoll {
  kind: "die_cut";
  widthMm: number | null;
  lengthMm: number | null;
}

/**
 * The roll the status shows, when it is one the hub cannot print on; null otherwise. Only a status that is a reading of the
 * printer now counts: a stale, unpolled or offline status says nothing about the roll. The hub refuses such a print with 409
 * `media_type_mismatch` too; this lets the UI say so before the press.
 */
export function unsupportedRoll(status: PrinterStatus | undefined): UnsupportedRoll | null {
  if (!status || status.polled === false || status.stale === true || status.online === false) return null;
  if (status.media_kind !== "die_cut") return null;
  return { kind: "die_cut", widthMm: status.tape_width_mm ?? null, lengthMm: status.label_length_mm ?? null };
}

/** "29 × 90 mm", or "29 mm" when the label length is not known; "" when not even the width is. */
export function rollSize(roll: UnsupportedRoll): string {
  if (roll.widthMm === null) return roll.lengthMm === null ? "" : `${roll.lengthMm} mm`;
  return roll.lengthMm === null ? `${roll.widthMm} mm` : `${roll.widthMm} × ${roll.lengthMm} mm`;
}

/** The same roll in one string for a notification entry id: one entry per printer and roll. */
export const rollKey = (roll: UnsupportedRoll): string => `${roll.kind}:${roll.widthMm ?? ""}x${roll.lengthMm ?? ""}`;

/** The id of a printer's roll entry in the notification centre; also the key of its first-seen time. */
export const rollEntryId = (printerId: string, roll: UnsupportedRoll): string => `printer:${printerId}:roll:${rollKey(roll)}`;

/**
 * When this browser first saw the roll that is in the printer now (ms), or null when it holds none the hub cannot print on
 * or the time is not known yet. A refusal counts only if it came after this: any roll change forgets older refusals.
 */
export function rollSinceMs(printerId: string, status: PrinterStatus | undefined, firstSeen: Readonly<Record<string, string>>): number | null {
  const roll = unsupportedRoll(status);
  if (!roll) return null;
  const at = Date.parse(firstSeen[rollEntryId(printerId, roll)] ?? "");
  return Number.isNaN(at) ? null : at;
}

export interface RollWords {
  /** "29 × 90 mm · Die-cut labels" */
  title: string;
  /** "29 × 90 mm die-cut labels", for running text */
  inline: string;
  /** "Unsupported roll loaded: 29 × 90 mm die-cut labels" */
  unsupported: string;
  /** "Printing on die-cut labels comes in a later version" */
  hint: string;
}

export function useRollWords(): (roll: UnsupportedRoll) => RollWords {
  const { t } = useLingui();
  return (roll) => {
    const size = rollSize(roll);
    const kind = t`Die-cut labels`;
    const lower = t({ message: "die-cut labels", comment: "In running text after a size, e.g. '29 × 90 mm die-cut labels'" });
    const inline = size ? `${size} ${lower}` : lower;
    return {
      title: size ? `${size} · ${kind}` : kind,
      inline,
      unsupported: t`Unsupported roll loaded: ${inline}`,
      hint: t`Printing on die-cut labels comes in a later version`,
    };
  };
}
