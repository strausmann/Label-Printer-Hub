import { useSheetType } from "../archive/api";
import { typeLabel } from "../sheets/typeLabel";
import type { Job } from "./api";
import { jobTitle, pageInfoOf } from "./model";

/** The sheet type's name for a key, or null until the type has been read (or when it is gone). */
export function useTypeLabel(key: string | null): string | null {
  const type = useSheetType(key ?? "", key !== null);
  return type.data ? typeLabel(type.data) : null;
}

/** `jobTitle` with the name of the calibration page's sheet type, which needs a query. */
export function useJobTitle(job: Job): string | null {
  const page = pageInfoOf(job);
  const label = useTypeLabel(page?.kind === "calibration_page" ? page.typeKey : null);
  return jobTitle(job, label);
}
