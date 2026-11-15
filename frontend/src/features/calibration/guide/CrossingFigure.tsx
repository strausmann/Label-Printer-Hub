// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import type { CalibrationScale } from "../api";
import { miniScaleTicks } from "../CalibrationSchematic";

/** Units of the drawing per millimetre on paper. */
const M = 40;

/**
 * Figure 1 of the reading guide: one crossing of the calibration page, drawn the way it looks on paper.
 * Black only (`currentColor`); the lines are told apart by style and number, never by colour. The drawing
 * carries digits and signs only; every word is in the legend next to it.
 *
 * The example: the middle of the gap lies 0.6 mm left of the printed S line and the row cut 0.4 mm above
 * the printed Z line, so the ink lies 0.6 mm right of the gap middle (across +0.6) and 0.4 mm below the
 * cut (down +0.4). 1 mm is 40 units; the scale is centred on the crossing at (120, 100).
 *
 * The numbers on the scale are the value to enter (the fit adds a reading to the nominal crossing: printed =
 * nominal + reading), not the position on the scale: where the gap middle falls left of 0 the ink lies right
 * of it, so the left side is + and the right side −; likewise the top is + and the bottom −. The Z line is
 * dotted because the drawn sheet has no gap between its rows, as the printed page does.
 *
 * The scale numbers are the only sign in the drawing: no arrow or mark states a plus side.
 *
 * The ticks of the scale are those of the printed page (`scale`, from `GET /api/v1/printers/calibration/scale`):
 * their spacing, lengths and stroke come from the backend's constants, drawn at the figure's 40 units per mm.
 * Without `scale` (still loading) the drawing has no ticks.
 *
 * Without `title` the drawing has no role and no name: the website page sets its own, localised ones.
 */
export function CrossingFigure({
  title,
  scale,
}: {
  title?: string;
  /** The mini scale of the printed page. */
  scale?: CalibrationScale;
  /** Accepted for symmetry with the export; this drawing has no ids. */
  idPrefix?: string;
}) {
  const ticks = scale ? miniScaleTicks(scale) : [];
  const a11y = title ? ({ role: "img", "aria-label": title } as const) : {};

  return (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="-8 -16 262 220" {...a11y}>
      {/* The labels: their outlines are the edges of the gap (1) and the cut (3). */}
      <g fill="none" stroke="currentColor" strokeWidth="0.8">
        <rect x="12" y="10" width="56" height="74" />
        <rect x="124" y="10" width="104" height="74" />
        <rect x="12" y="84" width="56" height="106" />
        <rect x="124" y="84" width="104" height="106" />
      </g>
      {/* The middle of the gap (2). */}
      <line x1="96" x2="96" y1="0" y2="196" stroke="currentColor" strokeWidth="1" strokeDasharray="1 3 7 3" />

      {/* The printed lines: S solid, Z dashed. */}
      <line x1="120" x2="120" y1="0" y2="196" stroke="currentColor" strokeWidth="1.8" />
      <line x1="0" x2="232" y1="100" y2="100" stroke="currentColor" strokeWidth="1.8" strokeDasharray="2 4" />

      {/* The scale, as printed: a tick every step, whole millimetres longer, the longest at 0. */}
      {scale && (
        <g stroke="currentColor" strokeWidth={scale.line_mm * M}>
          {ticks.map(({ offset, length }) => (
            <g key={offset}>
              <line x1={120 + offset * M} x2={120 + offset * M} y1={100 - (length / 2) * M} y2={100 + (length / 2) * M} />
              <line x1={120 - (length / 2) * M} x2={120 + (length / 2) * M} y1={100 + offset * M} y2={100 + offset * M} />
            </g>
          ))}
        </g>
      )}

      {/* The callouts 1 to 3 (edges of the gap, middle of the gap, the cut). */}
      <g fill="none" stroke="currentColor" strokeWidth="0.9">
        {(
          [
            ["1", 56, 22],
            ["1", 134, 170],
            ["2", 84, 192],
            ["3", 40, 70],
            ["3", 206, 70],
          ] as const
        ).map(([n, x, y]) => (
          <circle key={`${n}-${x}`} cx={x} cy={y} r="7" />
        ))}
      </g>

      {/* Digits and signs only. */}
      <g fill="currentColor" fontSize="10" textAnchor="middle">
        <text x="120" y="-6">S2</text>
        <text x="238" y="104" textAnchor="start">Z6</text>
        <text x="56" y="25.5">1</text>
        <text x="134" y="173.5">1</text>
        <text x="84" y="195.5">2</text>
        <text x="40" y="73.5">3</text>
        <text x="206" y="73.5">3</text>
        <text x="40" y="158">+2</text>
        <text x="80" y="158">+1</text>
        <text x="160" y="158">−1</text>
        <text x="200" y="158">−2</text>
        <text x="156" y="23.5" textAnchor="start">+2</text>
        <text x="156" y="63.5" textAnchor="start">+1</text>
        <text x="156" y="143.5" textAnchor="start">−1</text>
        <text x="156" y="183.5" textAnchor="start">−2</text>
        <text x="114" y="96" textAnchor="end">0</text>
      </g>
    </svg>
  );
}
