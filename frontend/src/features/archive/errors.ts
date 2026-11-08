import { useLingui } from "@lingui/react/macro";
import { ApiError } from "../../api/client";
import { invalidGeometry, prefixTaken, typeInUse } from "../../api/errorDetail";

/** The words for a failed archive request: the server's code first, its own text only as a last resort. */
export function useArchiveErrorText(): (error: unknown, fallback?: string) => string {
  const { t } = useLingui();
  return (error, fallback) => {
    if (error instanceof ApiError) {
      const geometry = invalidGeometry(error);
      if (geometry) return `${geometry.field}: ${geometry.reason}`;
      const prefix = prefixTaken(error);
      if (prefix) {
        return prefix.reason === "sheets_exist"
          ? t`The code prefix cannot change while sheets of this type exist.`
          : t`Another type already uses this code prefix.`;
      }
      const inUse = typeInUse(error);
      if (inUse) {
        return inUse.reason === "has_sheets"
          ? t`This type has sheets. Archive it instead.`
          : t`Only your own types can be deleted. Archive this one instead.`;
      }
      switch (error.code) {
        case "network_error":
          return t`The server cannot be reached.`;
        case "type_exists":
          return t`A sheet type with this key already exists.`;
        case "sheet_type_archived":
          return t`This type is archived. Bring it back first.`;
        case "sheet_type_not_found":
          return t`That sheet type does not exist.`;
        case "scope_too_low":
          return t`You need an admin key for this.`;
      }
      if (error.status === 403) return t`You need an admin key for this.`;
      if (error.detail && !/^HTTP \d+$/.test(error.detail)) return error.detail;
    }
    return fallback ?? t`Saving failed.`;
  };
}
