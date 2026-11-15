// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useLingui } from "@lingui/react/macro";
import { docsUrl } from "../../../shell/docsUrl";

/** The section of the docs page this card summarises, per UI language (the headings of using/calibration.mdx). */
const ANCHOR = { en: "printer-or-sheet-type", de: "drucker-oder-bogentyp" } as const;

/**
 * "Still off after the check print?": the four main rows of the table on labelyard.app (what you see, what it
 * means, what to do) in a form that reads at 390 px: one short block per row, no table. Static text, so the
 * on-screen keyboard is not involved; the link opens the full table in a new tab, as the guide's link does.
 */
export function StillOff() {
  const { t, i18n } = useLingui();
  const lang = i18n.locale === "de" ? "de" : "en";
  const rows = [
    { see: t`The whole page is off by the same shift`, todo: t`Calibrate: the correction removes it.` },
    { see: t`The deviation grows with the distance, on every sheet type`, todo: t`Calibrate: it is the scale or the rotation of the printer.` },
    { see: t`Only one sheet type is off; other sheets sit with the same correction`, todo: t`Correct that sheet type (add a new version), not the printer.` },
    { see: t`The shift differs from sheet to sheet`, todo: t`It is the paper feed: push the sheet against the guide and print a second one. Change the correction only if it repeats.` },
  ];
  return (
    <section aria-labelledby="still-off-h" className="flex flex-col gap-3">
      <h3 id="still-off-h" className="m-0 text-body font-bold">{t`Still off after the check print?`}</h3>
      <ul aria-label={t`What the deviation tells you`} className="m-0 flex list-none flex-col gap-2 p-0 text-small">
        {rows.map((row) => (
          <li key={row.see} className="flex flex-col gap-0.5 rounded-r2 bg-sunken p-3">
            <span className="font-bold">{row.see}</span>
            <span>{row.todo}</span>
          </li>
        ))}
      </ul>
      <a
        href={`${docsUrl("using/calibration", i18n.locale)}#${ANCHOR[lang]}`}
        target="_blank"
        rel="noopener noreferrer"
        className="inline-flex min-h-11 w-fit items-center text-small font-bold text-link underline underline-offset-2"
      >
        {t`More in the guide`}
        <span className="sr-only"> {t`(opens in a new tab)`}</span>
      </a>
    </section>
  );
}
