// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { crossingsToRead } from "../model";

// The page is drawn on a 200 × 280 sheet; the grid takes the middle of it. Cells are not to scale:
// the figure shows which crossings to read, not the measurements of the sheet type.
const GRID = { x: 34, y: 30, w: 144, h: 232 };

/**
 * Figure 2 of the reading guide: the grid of the chosen sheet type with the crossings to read marked and
 * numbered 1, 2, 3 … in the order of the list next to it. Black only (`currentColor`), digits and S/Z
 * numbers as the only text. Without `title` the drawing has no role and no name (the website export).
 */
export function SheetCrossingsFigure({ cols, rows, title }: { cols: number; rows: number; title?: string; /** Accepted for symmetry with CrossingFigure; this drawing has no ids. */ idPrefix?: string }) {
  const picks = crossingsToRead(cols, rows);
  const cw = GRID.w / cols;
  const ch = GRID.h / rows;
  const cells = Array.from({ length: cols * rows }, (_, i) => ({ c: i % cols, r: Math.floor(i / cols) }));
  const colGaps = [...new Set(picks.map((p) => p.col_gap))].sort((a, b) => a - b);
  const rowGaps = [...new Set(picks.map((p) => p.row_gap))].sort((a, b) => a - b);
  const a11y = title ? ({ role: "img", "aria-label": title } as const) : {};

  return (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 280" {...a11y}>
      <rect x="2" y="2" width="196" height="276" fill="none" stroke="currentColor" strokeWidth="1" />
      <g fill="none" stroke="currentColor" strokeWidth="0.5">
        {cells.map(({ c, r }) => (
          <rect key={`${c}-${r}`} x={GRID.x + c * cw + 0.75} y={GRID.y + r * ch + 0.75} width={cw - 1.5} height={ch - 1.5} />
        ))}
      </g>
      <g fill="currentColor" fontSize="8" textAnchor="middle">
        {colGaps.map((k) => (
          <text key={`s${k}`} x={GRID.x + k * cw} y={GRID.y - 7}>{`S${k}`}</text>
        ))}
        {rowGaps.map((k) => (
          <text key={`z${k}`} x={GRID.x - 6} y={GRID.y + k * ch + 2.8} textAnchor="end">{`Z${k}`}</text>
        ))}
      </g>
      {picks.map((p, i) => {
        const x = GRID.x + p.col_gap * cw;
        const y = GRID.y + p.row_gap * ch;
        return (
          <g key={`${p.col_gap}-${p.row_gap}`} data-crossing={`S${p.col_gap}-Z${p.row_gap}`} stroke="currentColor" fill="none">
            <circle cx={x} cy={y} r="5" strokeWidth="1.4" />
            <path d={`M${x - 9} ${y}H${x + 9}M${x} ${y - 9}V${y + 9}`} strokeWidth="0.7" />
            <text x={x + 8} y={y - 6} fill="currentColor" stroke="none" fontSize="11" fontWeight="700">{i + 1}</text>
          </g>
        );
      })}
    </svg>
  );
}
