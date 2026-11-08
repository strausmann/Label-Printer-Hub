import { useLingui } from "@lingui/react/macro";
import { Link } from "@tanstack/react-router";
import { ApiError } from "../../api/client";
import { cellsTaken, cellsUnconfirmed } from "../../api/errorDetail";

/** Why a retry or a cancel was refused, in words. Anything unknown ends in the plain fallback. */
export function RetryError({ error, sheetCode }: { error: unknown; sheetCode: string | null }) {
  const { t } = useLingui();
  if (error instanceof ApiError) {
    if (error.status === 0) return <>{t`The hub could not be reached. Try again.`}</>;
    const unconfirmed = cellsUnconfirmed(error);
    if (unconfirmed) {
      const cells = unconfirmed.cells.join(", ");
      return (
        <>
          {t`Cells ${cells} may or may not have been printed. Resolve them on the sheet first, then retry.`}{" "}
          {sheetCode && (
            <Link to="/sheets/$code" params={{ code: sheetCode }} className="font-bold text-link underline underline-offset-2">
              {t`Open ${sheetCode}`}
            </Link>
          )}
        </>
      );
    }
    const taken = cellsTaken(error);
    if (taken) {
      const cells = taken.cells.join(", ");
      return <>{t`Cells ${cells} are in use by something else now. Print the labels again as a new page.`}</>;
    }
    if (error.code === "job_not_retryable") return <>{t`This job cannot be retried: nothing is left to print.`}</>;
    if (error.code === "printer_disabled") return <>{t`The printer is switched off. Switch it on in the settings, then retry.`}</>;
  }
  return <>{t`The job could not be retried.`}</>;
}

export function CancelError({ error }: { error: unknown }) {
  const { t } = useLingui();
  if (error instanceof ApiError && error.status === 0) return <>{t`The hub could not be reached. Try again.`}</>;
  return <>{t`The job could not be cancelled.`}</>;
}
