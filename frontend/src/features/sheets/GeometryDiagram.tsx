import { useLingui } from "@lingui/react/macro";
import { asymmetryHints, formatMm, pageSizeMm, remainingMargins, type GeometryMm } from "./cellState";

/**
 * Read-only reference of a sheet type's measurements: a drawing of the top-left corner plus every
 * number in words (the drawing is for the eye, the list is the content). Margins right and bottom are
 * computed from the page size. The asymmetry hint is the server's (`SheetTypeRead.hints`) when given.
 */
export function GeometryDiagram({ geometry: g, hints }: { geometry: GeometryMm; hints?: string[] }) {
  const { t, i18n } = useLingui();
  const mm = (v: number) => formatMm(v, i18n.locale);
  const page = pageSizeMm(g);
  const { right, bottom } = remainingMargins(g);
  const active = hints ?? asymmetryHints(g);
  const round = g.shape === "round";
  const gapX = g.pitch_x - g.label_w;
  const gapY = g.pitch_y - g.label_h;

  const radius = round ? t`round` : g.corner_radius == null ? t`unknown` : mm(g.corner_radius);
  const rows: [string, string][] = [
    [t`Page`, `${g.page_size} · ${mm(page.w)} × ${mm(page.h)}`],
    [t`Label size`, `${mm(g.label_w)} × ${mm(g.label_h)}`],
    [t`Grid`, t`${g.cols} columns × ${g.rows} rows`],
    [t`Pitch`, `${mm(g.pitch_x)} × ${mm(g.pitch_y)}`],
    [t`Gap between columns`, mm(gapX)],
    [t`Gap between rows`, mm(gapY)],
    [t`Top margin`, mm(g.margin_top)],
    [t`Left margin`, mm(g.margin_left)],
    [t`Right margin`, mm(right)],
    [t`Bottom margin`, mm(bottom)],
    [t`Corner radius`, radius],
  ];

  // Drawing: two columns by two rows from the page corner, in mm.
  const cols = Math.min(2, g.cols);
  const rws = Math.min(2, g.rows);
  const vbW = g.margin_left + (cols - 1) * g.pitch_x + g.label_w + Math.max(g.margin_left, 4) * 0.6;
  const vbH = g.margin_top + (rws - 1) * g.pitch_y + g.label_h + Math.max(g.margin_top, 4) * 0.5;
  const labels = Array.from({ length: cols * rws }, (_, i) => ({
    x: g.margin_left + (i % cols) * g.pitch_x,
    y: g.margin_top + Math.floor(i / cols) * g.pitch_y,
  }));
  const dim = "stroke-link";
  const fs = Math.max(vbW, vbH) / 24;

  return (
    <div className="flex flex-col gap-4 sm:flex-row sm:items-start">
      <svg viewBox={`-1 -1 ${vbW + 2} ${vbH + 2}`} aria-hidden="true" className="block w-full max-w-72 shrink-0 self-center sm:self-start">
        <rect width={vbW} height={vbH} className="fill-surface stroke-line-strong" strokeWidth={vbW / 300} />
        {labels.map((l, i) =>
          round ? (
            <circle key={i} cx={l.x + g.label_w / 2} cy={l.y + g.label_h / 2} r={g.label_w / 2} className="fill-accent-soft stroke-accent" strokeWidth={vbW / 300} />
          ) : (
            <rect key={i} x={l.x} y={l.y} width={g.label_w} height={g.label_h} rx={g.corner_radius ?? 1} className="fill-accent-soft stroke-accent" strokeWidth={vbW / 300} />
          ),
        )}
        {/* label width and height on the first label, left and top margin to the page edge */}
        <line x1={g.margin_left} x2={g.margin_left + g.label_w} y1={g.margin_top - fs * 0.7} y2={g.margin_top - fs * 0.7} className={dim} strokeWidth={vbW / 300} />
        <line x1={g.margin_left - fs * 0.7} x2={g.margin_left - fs * 0.7} y1={g.margin_top} y2={g.margin_top + g.label_h} className={dim} strokeWidth={vbW / 300} />
        <line x1={0} x2={g.margin_left} y1={g.margin_top + g.label_h / 2} y2={g.margin_top + g.label_h / 2} className={dim} strokeWidth={vbW / 300} strokeDasharray={`${fs / 3} ${fs / 3}`} />
        <line x1={g.margin_left + g.label_w / 2} x2={g.margin_left + g.label_w / 2} y1={0} y2={g.margin_top} className={dim} strokeWidth={vbW / 300} strokeDasharray={`${fs / 3} ${fs / 3}`} />
        <text x={g.margin_left + g.label_w / 2} y={g.margin_top - fs * 1.1} fontSize={fs} textAnchor="middle" className="fill-ink-2">{mm(g.label_w)}</text>
      </svg>
      <div className="flex min-w-0 flex-1 flex-col gap-3">
        <dl className="m-0 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-small">
          {rows.map(([name, value]) => (
            <div key={name} className="contents">
              <dt className="text-ink-2">{name}</dt>
              <dd className="m-0 font-bold tabular-nums">{value}</dd>
            </div>
          ))}
        </dl>
        {active.length > 0 && (
          <div role="note" className="flex flex-col gap-1 rounded-r2 border border-warn bg-accent-soft p-3 text-small">
            {active.includes("margins_asymmetric_x") && (
              <p className="m-0">{t`The left and right margins differ (${mm(g.margin_left)} and ${mm(right)}). Measure the sheet again if the labels print off-centre.`}</p>
            )}
            {active.includes("margins_asymmetric_y") && (
              <p className="m-0">{t`The top and bottom margins differ (${mm(g.margin_top)} and ${mm(bottom)}). Measure the sheet again if the labels print off-centre.`}</p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
