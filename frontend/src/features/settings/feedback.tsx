import { useLingui } from "@lingui/react/macro";
import { ApiError } from "../../api/client";
import { ippRejected } from "../../api/errorDetail";

/** The words for a failed save: the server's code first, its own text only as a last resort. */
export function useErrorText(): (error: unknown, fallback?: string) => string {
  const { t } = useLingui();
  return (error, fallback) => {
    if (error instanceof ApiError) {
      switch (error.code) {
        case "network_error":
          return t`The server cannot be reached.`;
        case "setting_locked":
          return t`That value is set by the container and cannot be changed here.`;
        case "secret_required_for_new_url":
          return t`A secret is saved for the old URL. Enter the secret again to use the new URL.`;
        case "url_required_for_secret":
          return t`Set the URL first; a secret belongs to its URL.`;
        case "duplicate_slug":
          return t`That slug is already used by another printer.`;
        case "duplicate_name":
          return t`That name is already used by another printer.`;
        case "ipp_pdf_unsupported":
          return t`This printer cannot print PDF, which the hub needs for sheets.`;
        case "ipp_unreachable":
          return t`The printer cannot be reached at that address.`;
        case "ipp_rejected": {
          const status = ippRejected(error)?.ippStatus;
          return status ? t`The printer refused the request (${status}).` : t`The printer refused the request.`;
        }
        case "ipp_bad_response":
          return t`The address did not answer like an IPP printer.`;
        case "tray_unknown":
          return t`A tray is set that the printer does not report. Read the printer again.`;
        case "stored_connection_invalid":
          // The server's text names the printer by id; the operator's way out is the form, not the id.
          return t`The address saved for this printer is not valid. Enter the address again and save.`;
        case "invalid_connection":
          return t`The address or the certificate setting is not valid.`;
        case "scope_too_low":
          return t`You need an admin key for this.`;
      }
      if (error.status === 403) return t`You need an admin key for this.`;
      if (error.detail && !/^HTTP \d+$/.test(error.detail)) return error.detail;
    }
    return fallback ?? t`Saving failed.`;
  };
}

/** A line under a form: what went wrong (alert) or that it worked (status). */
export function SaveFeedback({ error, saved }: { error: string | null; saved: boolean }) {
  const { t } = useLingui();
  if (error) {
    return (
      <p role="alert" className="text-small text-ink">
        {error}
      </p>
    );
  }
  return (
    <p role="status" className="min-h-5 text-small text-ink-2">
      {saved ? t`Saved` : ""}
    </p>
  );
}
