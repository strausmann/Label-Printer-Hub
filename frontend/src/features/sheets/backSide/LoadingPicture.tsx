// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useLingui } from "@lingui/react/macro";
import type { TrayLoading } from "./loading";
import { backSideInstruction } from "./loading";

/** A small page: the front shows the label grid, the back the liner with the code strip. */
function Page({ x, y, side }: { x: number; y: number; side: "front" | "back" }) {
  return (
    <g transform={`translate(${x} ${y})`}>
      <rect width="42" height="58" rx="1.5" className="fill-surface stroke-ink-2" strokeWidth="1" />
      {side === "front"
        ? Array.from({ length: 24 }, (_, i) => (
            <rect key={i} x={3 + (i % 3) * 12.3} y={3 + Math.floor(i / 3) * 6.6} width="11.3" height="5.6" className="fill-sunken stroke-line-strong" strokeWidth="0.4" />
          ))
        : (
          <>
            <rect x="3" y="4" width="36" height="50" className="fill-sunken" />
            <rect x="7" y="7" width="6" height="16" className="fill-accent-soft stroke-accent" strokeWidth="0.9" />
          </>
        )}
    </g>
  );
}

/**
 * How to put the sheet in for the back (#350): turn it over along the long edge, then load it top edge
 * first with the liner facing the side the tray prints on. Drawn from the tray's loading, in the theme's
 * tokens so it reads in light and dark.
 */
export function LoadingPicture({ loading }: { loading: TrayLoading | null }) {
  const { t } = useLingui();
  const linerSide = loading ? backSideInstruction(loading).linerSide : "up";
  const sideWord = linerSide === "up" ? t`Liner side up` : t`Liner side down`;
  return (
    <figure className="m-0 flex flex-col gap-3 rounded-r3 bg-sunken p-4" data-testid="loading-picture">
      <svg viewBox="0 0 200 172" role="img" aria-label={loading ? t`Turn the sheet over along the long edge, then load it top edge first, ${sideWord}` : t`Turn the sheet over along the long edge, then load it top edge first`} className="block h-auto w-full max-w-72">
        <text x="2" y="10" fontSize="9" fontWeight="700" className="fill-ink">{t`1 Turn`}</text>
        <Page x={6} y={18} side="front" />
        <path d="M58 52 C78 22, 112 22, 132 48" fill="none" className="stroke-link" strokeWidth="2" markerEnd="url(#loading-arrow)" />
        <line x1="96" y1="16" x2="96" y2="82" className="stroke-link" strokeWidth="1" strokeDasharray="3 2" />
        <Page x={146} y={18} side="back" />
        <defs>
          <marker id="loading-arrow" viewBox="0 0 8 8" refX="6" refY="4" markerWidth="6" markerHeight="6" orient="auto">
            <path d="M0 0 L8 4 L0 8 z" className="fill-link" />
          </marker>
        </defs>
        <line x1="2" y1="88" x2="198" y2="88" className="stroke-line-strong" strokeWidth="0.8" />
        <text x="2" y="102" fontSize="9" fontWeight="700" className="fill-ink">{t`2 Load`}</text>
        <rect x="18" y="108" width="120" height="20" rx="3" className="fill-ink-2" />
        <rect x="30" y="124" width="96" height="3" rx="1.5" className="fill-ink" />
        <g transform="translate(52 118) scale(0.75)" opacity={linerSide === "down" ? 0.55 : 1}>
          <Page x={0} y={18} side="back" />
        </g>
        <path d="M68 168 L68 132" className="stroke-link" strokeWidth="2.2" markerEnd="url(#loading-arrow)" />
      </svg>
      <figcaption className="flex flex-wrap gap-2 text-small font-bold">
        <span className="rounded-full bg-link px-3 py-1 text-surface">{t`Top edge first`}</span>
        {loading ? <span className="rounded-full bg-link px-3 py-1 text-surface">{sideWord}</span> : null}
      </figcaption>
    </figure>
  );
}
