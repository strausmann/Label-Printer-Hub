import { useLingui } from "@lingui/react/macro";
import { getRouteApi, Link, useNavigate } from "@tanstack/react-router";
import type { ReactNode } from "react";
import { Button } from "react-aria-components";
import { ApiError } from "../../api/client";
import { PRIMARY_BUTTON } from "../../shell/SignIn";
import { StatusBadge } from "../../shell/StatusBadge";
import { usePrinters } from "../printers/api";
import { useJobStateBadge } from "../printers/model";
import { PANEL, SECONDARY_BUTTON, SECTION_HEADING } from "../ui";
import { useCancelJobById, useJob, useRetryJob, type Job } from "./api";
import { canCancel, canRetry, formatTime, historyOf, summarizePayload } from "./model";
import { PageJobInfo } from "./PageJobInfo";
import { CancelError, RetryError } from "./RetryError";
import { useJobTitle } from "./useJobTitle";

const route = getRouteApi("/jobs/$jobId");

export function JobPage() {
  const { t } = useLingui();
  const { jobId } = route.useParams();
  const job = useJob(jobId);
  if (job.isPending) return <p role="status" className="text-ink-2">{t`Loading…`}</p>;
  if (job.isError) {
    // A job of a printer the key may not use answers 404 as well: it reads as missing.
    const missing = job.error instanceof ApiError && job.error.status === 404;
    return (
      <div className="flex flex-col gap-3">
        <p role="alert">{missing ? t`This job does not exist.` : t`The job could not be loaded.`}</p>
        <Link to="/jobs" className="text-link underline underline-offset-2">
          {t`Back to the jobs`}
        </Link>
      </div>
    );
  }
  return <JobDetail job={job.data} />;
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt className="text-ink-2">{label}</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </>
  );
}

function JobDetail({ job }: { job: Job }) {
  const { t } = useLingui();
  const navigate = useNavigate();
  const stateOf = useJobStateBadge();
  const printers = usePrinters();
  const retry = useRetryJob();
  const cancel = useCancelJobById();
  const state = stateOf(job.state);
  const summary = summarizePayload(job);
  const title = useJobTitle(job);
  const cancelRequested = cancel.isSuccess && job.state === "printing";
  const printer = printers.data?.find((p) => p.id === job.printer_id);
  const printerLink = printer ? (
    <Link to="/printers/$printerId" params={{ printerId: printer.id }} className="text-link underline underline-offset-2">
      {printer.name}
    </Link>
  ) : (
    "—"
  );
  const { tapeMm, copyTotal } = summary;
  const copyNo = summary.copyIndex === null ? null : summary.copyIndex + 1;
  const stepLabel = { queued: t`Queued`, printing: t`Printing`, finished: stateOf(job.state).label };

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 flex-col gap-2">
          <h1 className="break-words text-title font-bold">{title ?? t`Label`}</h1>
          <StatusBadge state={state.badge} label={state.label} />
          <p className="code break-all text-small text-ink-2">{job.id}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {canRetry(job) && (
            <Button
              className={PRIMARY_BUTTON}
              isDisabled={retry.isPending}
              onPress={() =>
                retry.mutate(job.id, { onSuccess: (created) => void navigate({ to: "/jobs/$jobId", params: { jobId: created.id } }) })
              }
            >
              {t`Retry`}
            </Button>
          )}
          {canCancel(job) && !cancelRequested && (
            <Button className={SECONDARY_BUTTON} isDisabled={cancel.isPending} onPress={() => cancel.mutate(job.id)}>
              {t`Cancel`}
            </Button>
          )}
        </div>
      </header>

      {(retry.isError || cancel.isError) && (
        <p role="alert" className="text-small text-bad">
          {retry.isError ? (
            <RetryError error={retry.error} sheetCode={summary.page?.sheetCode ?? null} />
          ) : (
            <CancelError error={cancel.error} />
          )}
        </p>
      )}

      <PageJobInfo job={job} cancelRequested={cancelRequested} printer={printerLink} />

      {job.error && (
        <section aria-labelledby="error-h" className="rounded-r3 border border-bad bg-surface p-4">
          <h2 id="error-h" className={SECTION_HEADING}>{t`What went wrong`}</h2>
          <p role="alert" className="mt-2 whitespace-pre-wrap break-words">{job.error}</p>
        </section>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        {!summary.page && (
          <section aria-labelledby="payload-h" className={PANEL}>
            <h2 id="payload-h" className={SECTION_HEADING}>{t`What was printed`}</h2>
            <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-2">
              <Row label={t`Printer`}>{printerLink}</Row>
              <Row label={t`Title`}>{summary.title ?? "—"}</Row>
              <Row label={t`Code`}>{summary.code ? <span className="code">{summary.code}</span> : "—"}</Row>
              <Row label={t`Source`}>{summary.source ?? "—"}</Row>
              <Row label={t`Layout`}>{summary.contentType ? <span className="code">{summary.contentType}</span> : "—"}</Row>
              <Row label={t`Tape`}>{tapeMm !== null ? t`${tapeMm} mm` : "—"}</Row>
              <Row label={t`Copies`}>
                {copyTotal !== null && copyNo !== null ? t`${copyNo} of ${copyTotal}` : (summary.copies ?? "—")}
              </Row>
            </dl>
          </section>
        )}

        <section aria-labelledby="history-h" className={PANEL}>
          <h2 id="history-h" className={SECTION_HEADING}>{t`History`}</h2>
          <ol className="mt-3 flex flex-col gap-2">
            {historyOf(job).map((step) => (
              <li key={step.state} className="flex flex-wrap items-baseline justify-between gap-x-4 rounded-r2 bg-sunken px-3 py-2">
                <span className="font-bold">{stepLabel[step.state]}</span>
                <span className="text-small text-ink-2">{formatTime(step.at)}</span>
              </li>
            ))}
          </ol>
        </section>
      </div>
    </div>
  );
}
