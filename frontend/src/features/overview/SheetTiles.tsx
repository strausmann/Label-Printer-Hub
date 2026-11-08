import { useLingui } from "@lingui/react/macro";
import { Link } from "@tanstack/react-router";
import { useFeature } from "../../app/session";
import { ArchiveIcon, CalibrationIcon } from "../../shell/icons";
import { PANEL, SECTION_HEADING } from "../ui";

const TILE = `${PANEL} press flex min-h-20 items-center gap-3 font-bold`;

/**
 * Phone only (spec 5.3): the tab bar has room for Sheets, so the Overview carries the way to the
 * sheet archive and to the calibration. Same flags as the sidebar entries. Every scope that can open
 * the page gets the entry: the calibration page shows its read-only hint itself.
 */
export function SheetTiles() {
  const { t } = useLingui();
  const sheets = useFeature("sheets");
  const calibration = useFeature("calibration");
  if (!sheets && !calibration) return null;
  return (
    <section aria-labelledby="sheet-tiles-h" className="flex flex-col gap-3 lg:hidden">
      <h2 id="sheet-tiles-h" className={SECTION_HEADING}>{t`Sheets`}</h2>
      <ul className="grid grid-cols-2 gap-3">
        {sheets && (
          <li>
            <Link to="/sheets/archive" className={TILE}>
              <ArchiveIcon aria-hidden="true" className="shrink-0" />
              <span className="min-w-0 [overflow-wrap:anywhere]">{t`Sheet archive`}</span>
            </Link>
          </li>
        )}
        {calibration && (
          <li>
            <Link to="/calibration" className={TILE}>
              <CalibrationIcon aria-hidden="true" className="shrink-0" />
              <span className="min-w-0 [overflow-wrap:anywhere]">{t`Calibration`}</span>
            </Link>
          </li>
        )}
      </ul>
    </section>
  );
}
