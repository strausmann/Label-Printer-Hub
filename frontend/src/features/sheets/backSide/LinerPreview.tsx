// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useLingui } from "@lingui/react/macro";
import { useId } from "react";
import { placeStrip, type StripMm } from "./strip";

/**
 * The back of the liner, drawn to scale: the vendor print (shaded), its free strips and the code strip
 * where the hub puts it. Without a design the liner is plain and the strip sits at (10, 10) mm.
 */
export function LinerPreview({
  page,
  strips,
  code,
  className = "",
}: {
  page: { w: number; h: number };
  strips: readonly StripMm[];
  code?: string;
  className?: string;
}) {
  const { t } = useLingui();
  const pattern = `liner-${useId().replace(/[^a-zA-Z0-9]/g, "")}`;
  const where = placeStrip(strips);
  const printed = strips.length > 0;
  return (
    <svg
      viewBox={`-2 -2 ${page.w + 4} ${page.h + 4}`}
      role="img"
      aria-label={where ? t`Back of the liner with the sheet code strip` : t`Back of the liner: no free strip takes the sheet code`}
      className={`block h-auto w-full max-w-56 ${className}`}
      data-testid="liner-preview"
    >
      <defs>
        <pattern id={pattern} width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <line x1="0" y1="0" x2="0" y2="6" className="stroke-line-strong" strokeWidth="1.4" />
        </pattern>
      </defs>
      <rect x="0" y="0" width={page.w} height={page.h} rx="1.5" className="fill-surface stroke-line-strong" strokeWidth="0.6" />
      {printed && <rect x="0" y="0" width={page.w} height={page.h} rx="1.5" fill={`url(#${pattern})`} opacity="0.55" data-marker="vendor-print" />}
      {strips.map((s, i) => (
        <rect key={i} x={s.x_mm} y={s.y_mm} width={s.w_mm} height={s.h_mm} className="fill-surface stroke-line" strokeWidth="0.4" strokeDasharray="2 1.5" />
      ))}
      {where && (
        <g data-marker="code-strip">
          <rect x={where.x_mm} y={where.y_mm} width={where.w_mm} height={where.h_mm} rx="0.8" className="fill-accent-soft stroke-accent" strokeWidth="0.9" />
          <rect x={where.x_mm + 2.5} y={where.y_mm + 2.5} width="17" height="17" className="fill-ink" opacity="0.85" />
          <rect x={where.x_mm + 5} y={where.y_mm + 5} width="12" height="12" className="fill-accent-soft" />
          <rect x={where.x_mm + 7.5} y={where.y_mm + 7.5} width="7" height="7" className="fill-ink" opacity="0.85" />
          {code && (
            <text
              x={where.x_mm + 11}
              y={where.y_mm + where.h_mm - 3}
              fontSize="5"
              fontWeight="700"
              transform={`rotate(-90 ${where.x_mm + 11} ${where.y_mm + where.h_mm - 3})`}
              className="fill-ink font-mono"
            >
              {code}
            </text>
          )}
        </g>
      )}
    </svg>
  );
}
