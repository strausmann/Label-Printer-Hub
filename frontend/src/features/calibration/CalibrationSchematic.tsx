import { useLingui } from "@lingui/react/macro";
import { crossingName } from "./model";
import { cellRect, formatMm, pageSizeMm, type GeometryMm } from "../sheets/cellState";

/** The edge a gap line sits on: the middle of the gap, or the cut between two labels where there is none. */
const gapCentre = (start: number, pitch: number, size: number, k: number) => start + k * pitch - (pitch - size) / 2;

/**
 * A drawing of the calibration page of one sheet type, and its legend in words. The drawing is for
 * the eye (the numbers of the gap lines, where the scales sit); the legend says the same in text.
 * Black only, like the page itself: lines differ by number and style, never by colour.
 */
export function CalibrationSchematic({ geometry: g, typeName }: { geometry: GeometryMm; typeName: string }) {
  const { t, i18n } = useLingui();
  const page = pageSizeMm(g);
  const colGaps = Array.from({ length: g.cols - 1 }, (_, i) => i + 1);
  const rowGaps = Array.from({ length: g.rows - 1 }, (_, i) => i + 1);
  const noGapDown = g.pitch_y - g.label_h < 0.005;
  const noGapAcross = g.pitch_x - g.label_w < 0.005;
  const top = g.margin_top;
  const left = g.margin_left;
  const bottom = g.margin_top + (g.rows - 1) * g.pitch_y + g.label_h;
  const right = g.margin_left + (g.cols - 1) * g.pitch_x + g.label_w;
  const fs = 4;
  const hair = 0.25;
  const labels = Array.from({ length: g.cols * g.rows }, (_, i) => cellRect(g, i + 1));
  const mm = (v: number) => formatMm(v, i18n.locale);

  return (
    <div className="flex flex-col gap-4 sm:flex-row sm:items-start">
      <svg
        role="img"
        aria-label={t`Calibration page of ${typeName}: ${g.cols} columns and ${g.rows} rows on ${g.page_size}, ${mm(page.w)} × ${mm(page.h)}`}
        viewBox={`-6 -6 ${page.w + 12} ${page.h + 12}`}
        className="block w-full max-w-80 shrink-0 self-center text-ink sm:self-start"
      >
        <rect width={page.w} height={page.h} className="fill-surface stroke-line-strong" strokeWidth={0.4} />
        {labels.map((l, i) => (
          <rect key={i} x={l.x} y={l.y} width={l.w} height={l.h} fill="none" stroke="currentColor" strokeOpacity={0.25} strokeWidth={hair} />
        ))}
        {colGaps.map((k) => {
          const x = gapCentre(left, g.pitch_x, g.label_w, k);
          return (
            <g key={`s${k}`}>
              <line x1={x} x2={x} y1={top - 3} y2={bottom + 3} stroke="currentColor" strokeWidth={0.5} />
              <text x={x} y={top - 5} fontSize={fs} textAnchor="middle" fill="currentColor">{`S${k}`}</text>
            </g>
          );
        })}
        {rowGaps.map((k) => {
          const y = gapCentre(top, g.pitch_y, g.label_h, k);
          return (
            <g key={`z${k}`}>
              <line x1={left - 3} x2={right + 3} y1={y} y2={y} stroke="currentColor" strokeWidth={0.5} strokeDasharray="2 1.2" />
              <text x={left - 4.5} y={y + fs / 3} fontSize={fs} textAnchor="end" fill="currentColor">{`Z${k}`}</text>
            </g>
          );
        })}
        {colGaps.flatMap((s) =>
          rowGaps.map((z) => {
            const x = gapCentre(left, g.pitch_x, g.label_w, s);
            const y = gapCentre(top, g.pitch_y, g.label_h, z);
            return (
              <g key={`c${s}-${z}`} stroke="currentColor" strokeWidth={hair}>
                <line x1={x - 2} x2={x + 2} y1={y} y2={y} />
                <line x1={x} x2={x} y1={y - 2} y2={y + 2} />
              </g>
            );
          }),
        )}
      </svg>
      <ul aria-label={t`Legend`} className="m-0 flex min-w-0 flex-1 list-none flex-col gap-2 p-0 text-small">
        <li>{t`Printed in black only: lines are told apart by number and line style, never by colour.`}</li>
        <li>{t`S1, S2 … number the gaps between columns (solid lines).`}</li>
        <li>{t`Z1, Z2 … number the gaps between rows (dashed lines).`}</li>
        <li>{t`At every crossing sits a small scale: ±2 mm, a tick every 0.2 mm.`}</li>
        <li>{t`Rulers with a tick every 0.5 mm run along every gap line on all four edges of the grid.`}</li>
        {(noGapDown || noGapAcross) && (
          <li>
            {noGapDown && noGapAcross
              ? t`This sheet has no gap between its labels: the lines sit on the cuts. Peel every other label (checkerboard) if a cut is hard to see.`
              : noGapDown
                ? t`This sheet has no gap between its rows: the Z lines sit on the cuts. Peel every other label (checkerboard) if a cut is hard to see.`
                : t`This sheet has no gap between its columns: the S lines sit on the cuts. Peel every other label (checkerboard) if a cut is hard to see.`}
          </li>
        )}
      </ul>
    </div>
  );
}

/** One crossing, magnified: where the scales are and which way the two readings count. */
export function GapCrossing({ colGap, rowGap }: { colGap: number; rowGap: number }) {
  const { t } = useLingui();
  const name = crossingName(colGap, rowGap);
  const s = `S${colGap}`;
  const z = `Z${rowGap}`;
  const ticks = Array.from({ length: 21 }, (_, i) => i - 10);
  return (
    <section aria-label={t`Gap crossing ${name}`} className="flex flex-col gap-3 rounded-r2 bg-sunken p-3 sm:flex-row sm:items-center">
      <svg viewBox="-12 -12 24 24" aria-hidden="true" className="block w-full max-w-40 shrink-0 self-center text-ink">
        <line x1={-10} x2={10} y1={0} y2={0} stroke="currentColor" strokeWidth={0.3} strokeDasharray="1.2 0.8" />
        <line x1={0} x2={0} y1={-10} y2={10} stroke="currentColor" strokeWidth={0.3} />
        {ticks.map((i) => (
          <g key={i} stroke="currentColor" strokeWidth={0.15}>
            <line x1={i} x2={i} y1={-(i % 5 === 0 ? 1.2 : 0.6)} y2={i % 5 === 0 ? 1.2 : 0.6} />
            <line y1={i} y2={i} x1={-(i % 5 === 0 ? 1.2 : 0.6)} x2={i % 5 === 0 ? 1.2 : 0.6} />
          </g>
        ))}
        <path d="M3 -7 H9 M7.4 -8.4 L9 -7 L7.4 -5.6" fill="none" stroke="currentColor" strokeWidth={0.4} />
        <path d="M-7 3 V9 M-8.4 7.4 L-7 9 L-5.6 7.4" fill="none" stroke="currentColor" strokeWidth={0.4} />
      </svg>
      <div className="flex min-w-0 flex-col gap-2 text-small">
        <h3 className="m-0 text-body font-bold">{t`Gap crossing ${name}`}</h3>
        <p className="m-0">{t`Where gap line ${s} and gap line ${z} cross, read the small scales against the middle of the physical gap, in millimetres.`}</p>
        <p className="m-0">{t`Across: + = the ink lies to the right of the middle of the gap, − = to the left.`}</p>
        <p className="m-0">{t`Down: + = the ink lies below the middle of the gap, − = above it.`}</p>
      </div>
    </section>
  );
}
