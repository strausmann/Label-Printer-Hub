// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

/** Grocy's grocycode: `grcy:<p|b|c>:<id>` with optional `:<extra>` parts (a stock entry ID, a label). */
export const GROCYCODE_SCAN = /^grcy:(p|b|c):([0-9]+)(?::([^:]+))*$/;

export type GrocycodeEntity = "p" | "b" | "c";

export interface Grocycode {
  entity: GrocycodeEntity;
  id: string;
  extra: string[];
}

/** The product (`p`), battery (`b`) or chore (`c`) a scanned Grocycode names; null for anything else. */
export function parseGrocycode(text: string): Grocycode | null {
  const trimmed = text.trim();
  if (!GROCYCODE_SCAN.test(trimmed)) return null;
  const [, entity, id, ...extra] = trimmed.split(":");
  return { entity: entity as GrocycodeEntity, id: id!, extra };
}
