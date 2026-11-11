import { useLingui } from "@lingui/react/macro";

/**
 * Why a job failed, in the app's own words, from the code the hub stores (`error_code` of the event, or the
 * prefix of the job record's message). A code this list does not know gets a plain sentence plus the code,
 * never the hub's English message as the main text. The list is what the queue and the page-job runner emit
 * (`print_queue._ERROR_CODE_MAP`, `page_job_runner._MESSAGES`).
 */
export function useJobErrorText(): (code: string | null) => string {
  const { t } = useLingui();
  return (code) => {
    switch (code) {
      case "tape_mismatch":
        return t`The loaded tape does not match the label. Put in the right tape and retry.`;
      case "tape_empty":
        return t`The tape is empty. Put in a new tape and retry.`;
      case "printer_cover_open":
        return t`The printer cover is open. Close it and retry.`;
      case "printer_offline":
      case "ipp_unreachable":
        return t`The printer could not be reached. Check that it is switched on and connected, then retry.`;
      case "printer_status_unavailable":
        return t`The printer did not answer its status request.`;
      case "ipp_busy":
        return t`The printer was busy and did not take the job.`;
      case "ipp_rejected":
        return t`The printer refused the document.`;
      case "ipp_request_invalid":
        return t`The print request could not be built.`;
      case "render_timeout":
        return t`Drawing the page took too long.`;
      case "ipp_aborted":
        return t`The printer aborted the job before printing.`;
      case "interrupted":
        return t`The job was interrupted while it was printing. Check the printout before you retry.`;
      case "shutdown":
        return t`The hub was stopped before the job was printed.`;
      // #277: a tape batch that stopped after a group, and what a restart does to its waiting part.
      case "outcome_unknown":
        return t`The print stopped while this label was being sent. It may or may not have printed.`;
      case "not_started":
        return t`The print stopped before this label was sent.`;
      case "tape_run_interrupted":
        return t`The hub restarted while this label waited for the next part. Print it again.`;
      case "cancelled":
      case "cancelled_before_print":
        return t`The job was cancelled.`;
      case "batch_failed":
      case "print_failed":
        return t`The printer or the hub reported an error.`;
      case null:
      case undefined:
        return t`The printer or the hub reported an error.`;
      default:
        return t`The print failed (error code ${code}).`;
    }
  };
}
