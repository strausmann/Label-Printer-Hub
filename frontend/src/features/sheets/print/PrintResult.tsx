import { plural } from "@lingui/core/macro";
import { useLingui } from "@lingui/react/macro";
import { Link } from "@tanstack/react-router";
import type { SheetPrintResponse } from "../api";
import { useBandWord } from "./bandWord";

type Page = SheetPrintResponse["pages"][number];

const LINK = "inline-flex min-h-11 items-center text-link underline underline-offset-2";

/** "cells 18, 19, 20" in short: a run of three or more reads "18–26". */
function cellsWords(cells: number[]): string {
  const sorted = [...cells].sort((a, b) => a - b);
  const runs: string[] = [];
  for (let i = 0; i < sorted.length; ) {
    let j = i;
    while (j + 1 < sorted.length && sorted[j + 1] === sorted[j]! + 1) j++;
    const from = sorted[i]!;
    const to = sorted[j]!;
    runs.push(j - i >= 2 ? `${from}–${to}` : sorted.slice(i, j + 1).join(", "));
    i = j + 1;
  }
  return runs.join(", ");
}

/** What was queued: one line per page with its job, and the notes about the sheet ID that belong to that page. */
export function PrintResult({ pages }: { pages: Page[] }) {
  const { t } = useLingui();
  const bandWord = useBandWord();
  return (
    <section role="status" aria-labelledby="sheet-sent-h" className="flex flex-col gap-3 rounded-r2 border border-ok bg-sunken p-4">
      <h3 id="sheet-sent-h" className="font-bold">{t`Sent to the print queue`}</h3>
      <ol className="m-0 flex list-none flex-col gap-3 p-0">
        {pages.map((page, i) => {
          const number = i + 1;
          const code = page.sheet_code;
          const cells = cellsWords(page.cells);
          const band = bandWord(page.margin_band);
          return (
            <li key={page.job_id} className="flex min-w-0 flex-col gap-0.5">
              <span className="[overflow-wrap:anywhere]">{t`Page ${number}: ${code}, cells ${cells}`}</span>
              {page.id_not_printed ? (
                <span className="font-bold text-warn">{t`Sheet ID not printed, add it by hand`}</span>
              ) : page.margin_id ? (
                <span className="text-small text-ink-2">{t`Sheet ID in the ${band}`}</span>
              ) : null}
              <Link to="/jobs/$jobId" params={{ jobId: page.job_id }} className={LINK} aria-label={t`View job for page ${number}`}>
                {t`View job`}
              </Link>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

/** `502 print_interrupted`: part of the pages is queued and keeps printing; the rest was not queued. Never "could not be sent". */
export function PartialResult({ jobIds }: { jobIds: string[] }) {
  const { t } = useLingui();
  return (
    <div role="alert" className="flex flex-col gap-2 rounded-r2 border border-warn bg-sunken p-4">
      <p className="font-bold">
        {plural(jobIds.length, {
          one: "Only # page was queued, and it will print. The rest was not queued.",
          other: "Only # pages were queued, and they will print. The rest was not queued.",
        })}
      </p>
      <p>{t`The preview below shows what is left. Cells that are already in the queue count as used, so remove the labels that are queued from the cart first, or you get them twice.`}</p>
      <ol className="m-0 flex list-none flex-wrap gap-x-4 p-0">
        {jobIds.map((id, i) => {
          const number = i + 1;
          return (
            <li key={id}>
              <Link to="/jobs/$jobId" params={{ jobId: id }} className={LINK} aria-label={t`View job for page ${number}`}>
                {t`View job`}
              </Link>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
