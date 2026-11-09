import { useLingui } from "@lingui/react/macro";
import { ApiError } from "../../api/client";
import { useArchiveErrorText } from "../archive/errors";

/**
 * The words for a failed sheet request. The archive's table covers the type errors and the plain
 * ones; the sheet cases come first. Anything unknown ends in the fallback, never in a status code.
 */
export function useSheetErrorText(): (error: unknown, fallback?: string) => string {
  const { t } = useLingui();
  const archiveText = useArchiveErrorText();
  return (error, fallback) => {
    if (error instanceof ApiError) {
      switch (error.code) {
        case "sheet_busy":
          return t`A running job still uses this sheet. Try again when it has finished.`;
        case "sheet_not_found":
          return t`That sheet does not exist.`;
        case "sheet_discarded":
          return t`This sheet is discarded.`;
        case "printer_not_found":
          return t`That printer does not exist.`;
        case "printer_disabled":
          return t`This printer is switched off.`;
        case "printer-unavailable":
          return t`The print queue does not know this printer yet. Try again in a moment.`;
        case "tray_unknown":
          return t`The printer does not report that tray.`;
        case "cells_taken":
          return t`One of those cells is already in use. The sheet shows the current state.`;
        case "cells_not_marked_by_hand":
          return t`Only cells that were marked by hand can be un-marked.`;
        case "cells_not_unconfirmed":
          return t`Those cells are no longer waiting for confirmation.`;
        case "cell_out_of_range":
          return t`A marked cell is outside the sheet.`;
        case "ipp_unreachable":
          return t`The printer could not be reached.`;
        case "ipp_rejected":
        case "ipp_bad_response":
          return t`The printer did not accept the ID label.`;
      }
    }
    return archiveText(error, fallback);
  };
}
