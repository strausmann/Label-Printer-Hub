import { useLingui } from "@lingui/react/macro";
import { ApiError } from "../../api/client";
import { calibrationOutOfRange, readingsInsufficient } from "../../api/errorDetail";
import { useSheetErrorText } from "../sheets/errors";

/** The server's names of the five calibration values, as words (also the names the form uses). */
export function useValueNames(): Record<string, string> {
  const { t } = useLingui();
  return {
    offset_x_mm: t`Offset X`,
    offset_y_mm: t`Offset Y`,
    scale_x: t`Scale X`,
    scale_y: t`Scale Y`,
    rotation_deg: t`Rotation`,
  };
}

/** The allowed range of each value, for the sentence about a fitted value that is out of range. */
export function useRangeWords(): Record<string, string> {
  const { t } = useLingui();
  return {
    offset_x_mm: t`offset X (±10 mm)`,
    offset_y_mm: t`offset Y (±10 mm)`,
    scale_x: t`scale X (0.95 to 1.05)`,
    scale_y: t`scale Y (0.95 to 1.05)`,
    rotation_deg: t`rotation (±2°)`,
  };
}

/**
 * The words for a failed calibration request. Calibration cases come first; the rest is the sheet
 * screens' table (printer-unavailable, tray_unknown, no network, no admin key …).
 */
export function useCalibrationErrorText(): (error: unknown, fallback?: string) => string {
  const { t } = useLingui();
  const sheetText = useSheetErrorText();
  const names = useValueNames();
  return (error, fallback) => {
    if (error instanceof ApiError) {
      const range = calibrationOutOfRange(error);
      if (range) {
        const name = names[range.field] ?? range.field;
        if (range.reason === "too_many_decimals") return t`${name} has too many decimals.`;
        const { min, max } = range;
        return t`${name} must stay between ${min} and ${max}. More than that is a fault of the printer, not something to correct.`;
      }
      const insufficient = readingsInsufficient(error);
      if (insufficient) {
        switch (insufficient.reason) {
          case "fewer_than_three_readings":
            return t`Three readings are needed.`;
          case "readings_on_one_line":
            return t`All readings lie on one line. Read crossings that are far apart, in both directions.`;
          default:
            return t`These readings cannot be fitted. Check them and add crossings that are further apart.`;
        }
      }
      if (error.code === "invalid_geometry" && typeof error.errorDetail?.reading === "number") {
        const n = error.errorDetail.reading + 1;
        return t`Reading ${n} names a gap that this sheet does not have.`;
      }
      switch (error.code) {
        case "calibration_type_unsuitable":
          return t`This sheet type has fewer than two columns or two rows, so its calibration page has no crossings.`;
        case "media_kind_mismatch":
          return t`This is a tape printer. Calibration is only for page printers.`;
        case "sheet_type_version_not_found":
          return t`That version of the sheet type does not exist.`;
      }
    }
    return sheetText(error, fallback);
  };
}
