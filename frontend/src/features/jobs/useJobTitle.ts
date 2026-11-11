import { usePrinterStatus } from "../printers/api";
import { useSheetType } from "../archive/api";
import { typeLabel } from "../sheets/typeLabel";
import type { Job } from "./api";
import { jobTitle, pageInfoOf } from "./model";

/** The sheet type's name for a key, or null until the type has been read (or when it is gone). */
export function useTypeLabel(key: string | null): string | null {
  const type = useSheetType(key ?? "", key !== null);
  return type.data ? typeLabel(type.data) : null;
}

/**
 * The label of a test page's tray, from the printer's own status (the payload stores only the key).
 * Null until the status is read, or when the printer no longer reports that tray: callers fall back to the key.
 */
export function useTrayLabel(printerId: string, key: string | null): string | null {
  const status = usePrinterStatus(printerId, key !== null);
  return (key !== null && status.data?.trays?.find((tray) => tray.key === key)?.label) || null;
}

/** `jobTitle` with the name of the calibration page's sheet type, or of the test page's tray, which need a query. */
export function useJobTitle(job: Job): string | null {
  const page = pageInfoOf(job);
  const typeLabel = useTypeLabel(page?.kind === "calibration_page" ? page.typeKey : null);
  const trayLabel = useTrayLabel(job.printer_id, page?.kind === "test_page" ? page.tray : null);
  return jobTitle(job, typeLabel ?? trayLabel);
}
