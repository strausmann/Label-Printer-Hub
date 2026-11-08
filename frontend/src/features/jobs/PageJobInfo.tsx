import { useLingui } from "@lingui/react/macro";
import { Link } from "@tanstack/react-router";
import type { ReactNode } from "react";
import { useSheet } from "../sheets/api";
import { PANEL, SECTION_HEADING } from "../ui";
import type { Job } from "./api";
import { pageInfoOf } from "./model";
import { usePageJobStatus } from "./pageJobText";

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt className="text-ink-2">{label}</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </>
  );
}

const numbers = (cells: number[]) => cells.join(", ");

/** A job that stopped after cells were reserved: they may or may not have come out of the printer. */
const SETTLED_BY_HAND = new Set(["failed", "failed_restart", "cancelled"]);

/**
 * What a page job (a sheet page or a calibration page) adds to the job view: where it stands at
 * the printer, which sheet and cells it prints, and, after it stopped, the cells nobody has
 * confirmed yet with the way to settle them.
 */
export function PageJobInfo({ job, cancelRequested }: { job: Job; cancelRequested: boolean }) {
  const { t } = useLingui();
  const page = pageInfoOf(job);
  const status = usePageJobStatus(job);
  const code = page?.kind === "sheet_page" ? page.sheetCode : null;
  const sheet = useSheet(code !== null && SETTLED_BY_HAND.has(job.state) ? code : "");
  if (!page) return null;
  const unconfirmed = (sheet.data?.cells ?? []).filter((c) => c.state === "unconfirmed" && c.job_id === job.id).map((c) => c.cell);
  const discarded = sheet.data?.state === "discarded";
  const calibration = page.kind === "calibration_page";

  return (
    <section aria-labelledby="page-h" className={`${PANEL} flex flex-col gap-3`}>
      <h2 id="page-h" className={SECTION_HEADING}>
        {calibration ? t`Calibration page` : t`Sheet page`}
      </h2>
      {(status || cancelRequested) && (
        <div role="status" className="flex flex-col gap-1">
          {status && <p className="font-bold">{status}</p>}
          {cancelRequested && <p className="text-ink-2">{t`Asked the printer to cancel. The cells are settled when it reports.`}</p>}
        </div>
      )}
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2">
        {calibration ? (
          <Row label={t`Sheet type`}>{page.typeKey ? `${page.typeKey}${page.version === null ? "" : ` v${page.version}`}` : "—"}</Row>
        ) : (
          <>
            <Row label={t`Sheet`}>
              {code ? (
                <Link to="/sheets/$code" params={{ code }} className="code font-bold text-link underline underline-offset-2">
                  {code}
                </Link>
              ) : (
                "—"
              )}
            </Row>
            <Row label={t`Labels`}>{page.cellCount}</Row>
            <Row label={t`Cells`}>{page.cells.length > 0 ? <span className="code">{numbers(page.cells)}</span> : "—"}</Row>
            {page.idCell !== null && <Row label={t`Sheet ID in cell`}><span className="code">{page.idCell}</span></Row>}
          </>
        )}
      </dl>
      {unconfirmed.length > 0 && code && (
        <div className="rounded-r2 border border-bad bg-sunken p-3">
          <p className="font-bold">{t`Not confirmed`}</p>
          <p className="code break-words">{numbers(unconfirmed)}</p>
          <p className="mt-1 text-ink-2">
            {discarded
              ? t`The sheet is discarded, so these cells cannot be settled any more.`
              : t`The printer did not say whether these labels came out. Look at the sheet and settle each cell.`}
          </p>
          <Link to="/sheets/$code" params={{ code }} className="mt-2 inline-block font-bold text-link underline underline-offset-2">
            {discarded ? t`Open the sheet` : t`Settle the cells on the sheet`}
          </Link>
        </div>
      )}
    </section>
  );
}
