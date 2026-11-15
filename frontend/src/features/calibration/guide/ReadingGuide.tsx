// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useLingui } from "@lingui/react/macro";
import { useId, type ReactNode } from "react";
import { Button, Disclosure, DisclosurePanel, Heading } from "react-aria-components";
import { docsUrl } from "../../../shell/docsUrl";
import { centreCrossing, crossingName, crossingsToRead, suggestedCrossings } from "../model";
import { CrossingFigure } from "./CrossingFigure";
import { SheetCrossingsFigure } from "./SheetCrossingsFigure";

const FOCUS = "data-[focus-visible]:outline-3 data-[focus-visible]:outline-offset-2 data-[focus-visible]:outline-link";

/**
 * A legend list numbered with the circled digits of the drawing next to it. The digit is generated content
 * (a CSS counter), so a list item's text is only its words and a screen reader still announces a numbered list.
 */
const LEGEND =
  "m-0 flex list-none flex-col gap-1.5 p-0 [counter-reset:legend] [&>li]:flex [&>li]:items-start [&>li]:gap-2 [&>li]:[counter-increment:legend] " +
  "[&>li]:before:flex [&>li]:before:size-5 [&>li]:before:shrink-0 [&>li]:before:items-center [&>li]:before:justify-center [&>li]:before:rounded-full " +
  "[&>li]:before:border [&>li]:before:border-current [&>li]:before:text-[0.75rem] [&>li]:before:font-bold [&>li]:before:content-[counter(legend)]";

/** A drawing in a box of its own width; the SVG fills it, so it fits 390 px without scrolling sideways. */
const FIGURE = "w-full text-ink [&>svg]:block [&>svg]:h-auto [&>svg]:w-full";

/**
 * "How to read the calibration page": a collapsed panel at the top of step 2 with the drawing of one
 * crossing, the steps (with the drawing of the chosen sheet type) and a link to the same page on
 * labelyard.app. The drawings carry digits only; the words are the lists beside them.
 */
export function ReadingGuide({ type }: { type?: { geometry: { cols: number; rows: number }; label: string } }) {
  const { t, i18n } = useLingui();
  const locale = i18n.locale;
  const stepsId = useId();
  const geometry = type?.geometry;
  const typeName = type?.label ?? "";
  const outer = geometry ? suggestedCrossings(geometry.cols, geometry.rows) : [];
  const centre = geometry ? centreCrossing(geometry.cols, geometry.rows) : null;
  // The readings helper is offered only when the crossings do not all lie on one line (ReadingsHelper).
  const fits = !geometry || (geometry.cols > 2 && geometry.rows > 2);
  const isOuter = (c: { col_gap: number; row_gap: number }) => outer.some((o) => o.col_gap === c.col_gap && o.row_gap === c.row_gap);

  return (
    <Disclosure className="rounded-r2 bg-sunken">
      <Heading level={3} className="m-0">
        <Button
          slot="trigger"
          className={`press flex min-h-11 w-full items-center justify-between gap-3 rounded-r2 px-3 py-2 text-left text-body font-bold text-ink ${FOCUS} group`}
        >
          <span>{t`How to read the calibration page`}</span>
          <svg
            aria-hidden="true"
            viewBox="0 0 12 12"
            className="size-3 shrink-0 transition-transform duration-200 ease-out group-aria-expanded:rotate-90 motion-reduce:transition-none"
          >
            <path d="M4 1.5 8.5 6 4 10.5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </Button>
      </Heading>
      <DisclosurePanel className="h-(--disclosure-panel-height) overflow-clip transition-[height] duration-200 ease-out motion-reduce:transition-none">
        <div className="flex flex-col gap-5 px-3 pt-1 pb-4 text-small">
          <Block
            figure={<CrossingFigure title={t`How to read one crossing`} />}
            legend={
              <>
                <ol aria-label={t`Parts of the crossing`} className={LEGEND}>
                  <li>{t`The two edges of the gap between two columns: the sides of the labels.`}</li>
                  <li>{t`The middle of that gap (dash-dot line). The printed line should lie here.`}</li>
                  <li>{t`The cut between two rows.`}</li>
                </ol>
                <ul aria-label={t`Lines, scale and arrows`} className="m-0 flex list-disc flex-col gap-1.5 pl-5">
                  <li>{t`Heavy solid line: the printed S line. Heavy dashed line: the printed Z line (dotted on a sheet without a gap between the rows, as in the drawing).`}</li>
                  <li>{t`The numbers on the scale are the value to enter when the middle of the gap (across) or the cut (down) falls there.`}</li>
                  <li>{t`The scale lies on both lines: 0 on the printed line, a long tick every 1 mm, a short tick every 0.2 mm, up to ±2 mm.`}</li>
                  <li>{t`Example: the middle of the gap lies 0.6 mm left of the printed line and the cut 0.4 mm above it. The scale reads +0.6 and +0.4 there, so across is +0.6 and down is +0.4.`}</li>
                </ul>
              </>
            }
          />

          <h4 id={stepsId} className="m-0 text-body font-bold">{t`Steps`}</h4>
          <ol aria-labelledby={stepsId} className="m-0 -mt-2 flex list-decimal flex-col gap-3 pl-5">
            <li>{t`Print the page on a real sheet of this type. Writing a number on each cell, row by row, is optional; it helps when you take photos.`}</li>
            <li className="flex flex-col gap-3">
              <span>{fits ? t`Read at least the four outer crossings and the one in the centre.` : t`Read the crossings marked in the drawing.`}</span>
              {geometry && (
                <Block
                  figure={<SheetCrossingsFigure cols={geometry.cols} rows={geometry.rows} title={t`The crossings to read on ${typeName}`} />}
                  legend={
                    <>
                      <ol aria-label={t`The crossings to read`} className={LEGEND}>
                        {crossingsToRead(geometry.cols, geometry.rows).map((c) => {
                          const name = crossingName(c.col_gap, c.row_gap);
                          const isCentre = centre !== null && c.col_gap === centre.col_gap && c.row_gap === centre.row_gap && !isOuter(c);
                          return <li key={name}>{isCentre ? t`${name} (centre)` : name}</li>;
                        })}
                      </ol>
                      <p className="m-0">{t`The numbers in the drawing follow this list. S counts the gaps between columns from the left, Z the gaps between rows from the top.`}</p>
                    </>
                  }
                />
              )}
            </li>
            <li>{t`At a crossing, look where the middle of the gap (across) or the cut (down) falls on the scale, and count its distance from the printed line. Between two ticks, estimate to 0.1 mm by eye.`}</li>
            <li className="flex flex-col gap-1">
              <span>{t`+ across = the ink lies right of the middle of the gap, − across = left of it.`}</span>
              <span>{t`+ down = the ink lies below the cut, − down = above it.`}</span>
            </li>
            <li>{t`If the sheet has no gap between the rows, the Z line sits on the cut. Peel off every other label (checkerboard) only if the cut is hard to see.`}</li>
            <li>
              {fits
                ? t`Enter the readings below, choose the crossing for each, and press Fit. Check the filled-in values, then save them.`
                : t`On this sheet all crossings lie on one line, so the readings cannot be fitted. Enter the values directly in the form below, then save them.`}
            </li>
            <li>{t`Print the check page in step 3. If every crossing is within ±0.5 mm, you are done; if not, measure again.`}</li>
            <li>{t`Printer or sheet type? Deviations that grow evenly across the page (offset, scale, rotation) come from the printer; the fit corrects them. A jump between neighbouring gaps comes from the geometry of the sheet type: correct the sheet type first, then calibrate.`}</li>
          </ol>

          <a
            href={docsUrl("using/calibration", locale)}
            target="_blank"
            rel="noopener noreferrer"
            className="w-fit font-bold text-link underline underline-offset-2"
          >
            {t`More on labelyard.app`}
            <span className="sr-only"> {t`(opens in a new tab)`}</span>
          </a>
        </div>
      </DisclosurePanel>
    </Disclosure>
  );
}

/** A drawing and its legend: side by side from the small breakpoint up, stacked on a phone. */
function Block({ figure, legend }: { figure: ReactNode; legend: ReactNode }) {
  return (
    <div className="flex flex-col gap-3 sm:grid sm:grid-cols-[minmax(0,17rem)_minmax(0,1fr)] sm:items-start sm:gap-5">
      <div className={`${FIGURE} max-w-sm`}>{figure}</div>
      <div className="flex min-w-0 flex-col gap-3">{legend}</div>
    </div>
  );
}
