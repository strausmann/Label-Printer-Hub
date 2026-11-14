// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { plural } from "@lingui/core/macro";
import { useLingui } from "@lingui/react/macro";
import { Button } from "react-aria-components";
import { SECONDARY_BUTTON } from "../../ui";
import type { SheetSummary } from "../api";
import { fittingFirst, freeOf, placementFor, type Fill, type PlacementIn, type Target } from "./plan";

export interface CapacityAlertProps {
  /** Labels in this print. */
  needed: number;
  /** The server's capacity per placement (a count each); the alert is about the first one, the print's target. */
  capacity: readonly number[];
  target: Target;
  typeKey: string;
  fill: Fill;
  /** The other usable sheets of the type. */
  others: readonly SheetSummary[];
  onChoose: (choice: { placements: PlacementIn[]; target?: Target }) => void;
}

/** At most this many sheets are offered to take the print instead. */
const MAX_OFFERED = 3;

/**
 * The sheet has no room for a single label of this print (`insufficient_cells`). One run prints one sheet
 * (#277), so the way on is another sheet of the type: the ones with the most room are offered first.
 */
export function CapacityAlert({ needed, capacity, target, typeKey, fill, others, onChoose }: CapacityAlertProps) {
  const { t } = useLingui();
  const free = Math.max(0, capacity[0] ?? 0);
  const code = target.kind === "sheet" ? target.code : t`The new sheet`;
  const candidates = others.filter((s) => (target.kind !== "sheet" || s.code !== target.code) && freeOf(s) > 0);
  const roomy = fittingFirst(candidates, needed).slice(0, MAX_OFFERED);

  return (
    <div role="alert" className="flex flex-col gap-3 rounded-r2 border border-warn bg-sunken p-4">
      <p className="font-bold">
        {plural(free, {
          one: `${code} has only # free cell, and this print needs ${needed}.`,
          other: `${code} has only # free cells, and this print needs ${needed}.`,
        })}
      </p>
      {roomy.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {roomy.map(({ sheet }) => {
            const room = freeOf(sheet);
            const roomyCode = sheet.code;
            return (
              <Button
                key={sheet.code}
                className={SECONDARY_BUTTON}
                onPress={() => onChoose({ placements: [placementFor({ kind: "sheet", code: sheet.code }, typeKey, { ...fill, mode: "first_free" })], target: { kind: "sheet", code: sheet.code } })}
              >
                {t`Use ${roomyCode} instead (${room} free)`}
              </Button>
            );
          })}
        </div>
      )}
      {roomy.length === 0 && <p className="text-small text-ink-2">{t`No other sheet of this type has a free cell.`}</p>}
    </div>
  );
}
