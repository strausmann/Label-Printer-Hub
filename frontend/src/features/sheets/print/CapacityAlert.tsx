import { plural } from "@lingui/core/macro";
import { useLingui } from "@lingui/react/macro";
import { Button } from "react-aria-components";
import { SECONDARY_BUTTON } from "../../ui";
import type { SheetSummary } from "../api";
import { fittingFirst, freeOf, placementFor, splitPlacements, type Fill, type PlacementIn, type Target } from "./plan";

export interface CapacityAlertProps {
  /** Labels in this print. */
  needed: number;
  /**
   * The server's capacity per placement (a count each). The alert is about the print's target, the
   * first placement; when an earlier split was already too big, the split is rebuilt from that target.
   */
  capacity: readonly number[];
  target: Target;
  typeKey: string;
  fill: Fill;
  /** The other usable sheets of the type. */
  others: readonly SheetSummary[];
  /** False for an archived type: the rest cannot go onto a new sheet. */
  allowNew?: boolean;
  onChoose: (choice: { placements: PlacementIn[]; target?: Target }) => void;
}

/** At most this many sheets are offered to take the whole print. */
const MAX_OFFERED = 3;

/**
 * The sheet is too small for the print (`insufficient_cells`). Three ways on, each building the
 * placements of the next preview: the rest onto another sheet of the type, the rest onto a new
 * sheet, or the whole print onto a sheet that has room for it.
 */
export function CapacityAlert({ needed, capacity, target, typeKey, fill, others, allowNew = true, onChoose }: CapacityAlertProps) {
  const { t } = useLingui();
  const free = Math.max(0, capacity[0] ?? 0);
  const code = target.kind === "sheet" ? target.code : t`The new sheet`;
  const shortfall = needed - free;
  const candidates = others.filter((s) => target.kind !== "sheet" || s.code !== target.code);
  const restSheet = fittingFirst(candidates, shortfall).find((r) => r.fits)?.sheet ?? null;
  const roomy = fittingFirst(candidates, needed)
    .filter((r) => r.fits)
    .slice(0, MAX_OFFERED);
  const rest = (next: Target) => onChoose({ placements: splitPlacements(target, typeKey, fill, free, next) });
  const restCode = restSheet?.code ?? "";

  return (
    <div role="alert" className="flex flex-col gap-3 rounded-r2 border border-warn bg-sunken p-4">
      <p className="font-bold">
        {plural(free, {
          one: `${code} has only # free cell, and this print needs ${needed}.`,
          other: `${code} has only # free cells, and this print needs ${needed}.`,
        })}
      </p>
      <div className="flex flex-wrap gap-2">
        {restSheet && (
          <Button className={SECONDARY_BUTTON} onPress={() => rest({ kind: "sheet", code: restCode })}>
            {t`Put the rest onto ${restCode}`}
          </Button>
        )}
        {allowNew && (
          <Button className={SECONDARY_BUTTON} onPress={() => rest({ kind: "new" })}>
            {t`Put the rest onto a new sheet`}
          </Button>
        )}
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
      {roomy.length === 0 && <p className="text-small text-ink-2">{t`No other sheet of this type has room for all of it.`}</p>}
    </div>
  );
}
