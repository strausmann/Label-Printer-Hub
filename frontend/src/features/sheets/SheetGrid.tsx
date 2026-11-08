import { useLingui } from "@lingui/react/macro";
import { useCallback, useLayoutEffect, useId, useMemo, useRef, useState, type KeyboardEvent, type RefObject } from "react";
import {
  CELL_STATES,
  cellLabel,
  cellRect,
  cellStateWord,
  gridLayout,
  type GeometryMm,
  type GridCell,
  type GridCellState,
  type GridMode,
  type Translate,
} from "./cellState";

/** What a phone is assumed to be until the container has been measured (and in jsdom). */
const FALLBACK_WIDTH_PX = 360;

/**
 * Width of the element in px, kept up to date. Tolerates a missing `ResizeObserver` (jsdom, very old
 * browsers) by staying at the fallback; tests inject the width instead.
 */
function useContainerWidth(ref: RefObject<HTMLElement | null>, injected?: number): number {
  const [measured, setMeasured] = useState(FALLBACK_WIDTH_PX);
  // Layout effect: the first paint already has the measured width (no 360 px flash on a wide screen).
  useLayoutEffect(() => {
    const el = ref.current;
    if (injected !== undefined || !el || typeof ResizeObserver === "undefined") return;
    const measure = () => {
      const width = Math.round(el.clientWidth);
      if (width > 0) setMeasured(width);
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, [ref, injected]);
  return injected ?? measured;
}

// The five fills below are tokens only (src/design/tokens.css), so both themes follow.
// Every state also carries a marker that is not a colour: hatch, clock, question mark, fill, cross, dashes.
const SHAPE_CLASS: Record<GridCellState, string> = {
  free: "fill-transparent stroke-line-strong",
  used: "fill-sunken stroke-ink-3",
  reserved: "fill-accent-soft stroke-accent",
  unconfirmed: "fill-surface stroke-warn",
  new: "fill-accent stroke-accent-ink",
  skipped: "fill-sunken stroke-ink-3",
};
// Over a rendered page (`overlayPng`) the state must not hide the preview: outline and marker only, no fill.
const OVERLAY_CLASS: Record<GridCellState, string> = {
  free: "fill-transparent stroke-line-strong",
  used: "fill-transparent stroke-ink-3",
  reserved: "fill-transparent stroke-accent",
  unconfirmed: "fill-transparent stroke-warn",
  new: "fill-transparent stroke-accent",
  skipped: "fill-transparent stroke-ink-3",
};
const STROKE_W: Record<GridCellState, number> = { free: 0.35, used: 0.3, reserved: 0.4, unconfirmed: 0.8, new: 0.4, skipped: 0.3 };
const DASH: Partial<Record<GridCellState, string>> = { free: "1.4 1", skipped: "1.2 0.9" };

function StatePatterns({ id }: { id: string }) {
  return (
    <defs>
      <pattern id={id} patternUnits="userSpaceOnUse" width="1.8" height="1.8" patternTransform="rotate(45)">
        <line x1="0" y1="0" x2="0" y2="1.8" className="stroke-ink-3" strokeWidth="0.5" />
      </pattern>
    </defs>
  );
}

interface BodyProps {
  state: GridCellState;
  x: number;
  y: number;
  w: number;
  h: number;
  round: boolean;
  radius: number;
  patternId: string;
  /** Printed in the cell when set. */
  number?: number;
  numberMm?: number;
  isId?: boolean;
  hwMargin?: boolean;
  hoverable?: boolean;
  /** Drawn over the page image: outlines and markers only. */
  overlay?: boolean;
}

/** One cell, drawn in mm: the shape of its state plus the non-colour marker, number and flags. */
function CellBody({ state, x, y, w, h, round, radius, patternId, number, numberMm = 3.5, isId, hwMargin, hoverable, overlay }: BodyProps) {
  const cx = x + w / 2;
  const cy = y + h / 2;
  const r = w / 2;
  const glyph = Math.min(5, Math.min(h, w) * 0.5);
  // Rectangles: number left, glyph right. Round cells: number centred, glyph lower right.
  const gx = round ? cx + r * 0.5 : x + w - glyph * 0.5 - 1.4;
  const gy = round ? cy + r * 0.5 : cy;
  const shapeProps = {
    "data-shape": "cell",
    className: `${overlay ? OVERLAY_CLASS[state] : SHAPE_CLASS[state]} ${hoverable ? "group-hover/cell:stroke-link" : ""}`,
    strokeWidth: overlay && state === "new" ? 1 : STROKE_W[state],
    strokeDasharray: DASH[state],
    "data-marker": state === "free" ? "free" : state === "new" ? "filled" : undefined,
  };
  const shape = (extra: Record<string, unknown> = {}) =>
    round ? (
      <circle cx={cx} cy={cy} r={r} {...shapeProps} {...extra} />
    ) : (
      <rect x={x} y={y} width={w} height={h} rx={radius} {...shapeProps} {...extra} />
    );
  const inset = 1.5;
  return (
    <g data-state={state}>
      {shape()}
      {state === "used" &&
        (round ? (
          <circle cx={cx} cy={cy} r={r} fill={`url(#${patternId})`} data-marker="hatch" pointerEvents="none" opacity={overlay ? 0.4 : 1} />
        ) : (
          <rect x={x} y={y} width={w} height={h} rx={radius} fill={`url(#${patternId})`} data-marker="hatch" pointerEvents="none" opacity={overlay ? 0.4 : 1} />
        ))}
      {state === "skipped" && (
        <line
          data-marker="cross"
          x1={round ? cx - r * 0.55 : x + inset}
          y1={round ? cy - r * 0.55 : y + inset}
          x2={round ? cx + r * 0.55 : x + w - inset}
          y2={round ? cy + r * 0.55 : y + h - inset}
          className="stroke-ink-3"
          strokeWidth="0.5"
          pointerEvents="none"
        />
      )}
      {state === "reserved" && (
        <g data-marker="clock" transform={`translate(${gx} ${gy})`} fill="none" className="stroke-ink" strokeWidth="0.6" pointerEvents="none">
          <circle r={glyph / 2} />
          <polyline points={`0,${-glyph * 0.3} 0,0 ${glyph * 0.22},${glyph * 0.12}`} strokeLinecap="round" strokeLinejoin="round" />
        </g>
      )}
      {state === "unconfirmed" && (
        <text
          data-marker="question"
          x={gx}
          y={gy}
          fontSize={glyph * 1.25}
          fontWeight="700"
          textAnchor="middle"
          dominantBaseline="central"
          className="fill-warn"
          pointerEvents="none"
        >
          ?
        </text>
      )}
      {number !== undefined && (
        <text
          x={round ? cx : x + 1.6}
          y={round ? cy - (isId ? r * 0.15 : 0) : cy}
          fontSize={numberMm}
          fontWeight={state === "new" ? 800 : 600}
          textAnchor={round ? "middle" : "start"}
          dominantBaseline="central"
          className={`select-none ${state === "new" && !overlay ? "fill-accent-ink" : "fill-ink-2"} ${overlay ? "stroke-surface" : state === "used" ? "stroke-sunken" : "stroke-transparent"}`}
          strokeWidth={overlay || state === "used" ? 0.7 : 0}
          paintOrder="stroke"
          pointerEvents="none"
        >
          {number}
        </text>
      )}
      {isId && (
        <text
          data-marker="id"
          x={round ? cx : x + 1.6 + String(number ?? "").length * numberMm * 0.62 + 1.2}
          y={round ? cy + r * 0.45 : cy}
          fontSize={numberMm * 0.72}
          fontWeight="800"
          textAnchor={round ? "middle" : "start"}
          dominantBaseline="central"
          className={`select-none ${state === "new" && !overlay ? "fill-accent-ink" : "fill-ink"}`}
          pointerEvents="none"
        >
          ID
        </text>
      )}
      {hwMargin && (
        <circle
          data-marker="hw-margin"
          cx={round ? cx + r * 0.7 : x + w - 1.4}
          cy={round ? cy - r * 0.7 : y + 1.4}
          r="1"
          className="fill-warn stroke-surface"
          strokeWidth="0.3"
          pointerEvents="none"
        />
      )}
    </g>
  );
}

const defaultSelectable = (mode: GridMode) => (cell: GridCell) =>
  mode === "select" ? cell.state === "free" : mode === "skip" ? cell.state === "new" : false;

export interface SheetGridProps {
  geometry: GeometryMm;
  cells: GridCell[];
  mode: GridMode;
  onToggle?: (cell: number) => void;
  /** Called with a cell's number when it gets focus or a tap, in every mode: the page shows what the cell holds. */
  onInspect?: (cell: number) => void;
  /** Rendered sheet page (data URL), drawn under the cells over the whole page. */
  overlayPng?: string;
  zoom?: 1 | 2;
  /** Accessible name of the grid, e.g. the sheet code. */
  label: string;
  /** Which cells can be toggled. Default: free cells in `select`, planned `new` cells in `skip`. */
  selectable?: (cell: GridCell) => boolean;
  /** Test seam: skips measuring the container. */
  containerWidth?: number;
}

/**
 * The cells of a label sheet at the sheet's true aspect ratio, as an ARIA grid.
 * Arrow keys move, Home/End jump to the row ends, Space or Enter toggles in `select`/`skip`.
 * On phones, selecting opens a zoomed view in its own scroll container so every cell is at least
 * 44 × 44 px (spec 17.6); the page itself never scrolls sideways.
 */
export function SheetGrid({ geometry: g, cells, mode, onToggle, onInspect, overlayPng, zoom = 1, label, selectable, containerWidth }: SheetGridProps) {
  const { i18n } = useLingui();
  const t = useCallback<Translate>((d) => i18n._(d), [i18n]);
  const wrapRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const width = useContainerWidth(wrapRef, containerWidth);
  const layout = gridLayout(g, width, mode, zoom, !!onInspect);
  const patternId = `hatch-${useId().replace(/[^a-zA-Z0-9]/g, "")}`;
  const total = g.cols * g.rows;
  const [active, setActive] = useState(1);

  const byNumber = useMemo(() => new Map(cells.map((c) => [c.cell, c])), [cells]);
  const canToggle = selectable ?? defaultSelectable(mode);
  const interactive = mode !== "view";
  const round = g.shape === "round";
  const radius = g.corner_radius ?? 1; // unknown radius: a slight rounding, the label shows "unknown"
  // Numbers are 14 px at most, however large the cell grows (a 1 x 7 lever-arch sheet has 190 mm wide cells).
  const numberMm = Math.min(g.label_h * 0.45, g.label_w * 0.3, 14 / layout.scale);
  const showNumbers = numberMm * layout.scale >= 7;
  const ringMm = 3 / layout.scale;

  const focusCell = (n: number) => {
    setActive(n);
    svgRef.current?.querySelector<SVGElement>(`[data-cell="${n}"]`)?.focus();
  };

  const toggle = (data: GridCell) => {
    onInspect?.(data.cell);
    if (interactive && onToggle && canToggle(data)) onToggle(data.cell);
  };

  const onKeyDown = (event: KeyboardEvent, n: number, data: GridCell) => {
    const col = (n - 1) % g.cols;
    let next = n;
    switch (event.key) {
      case "ArrowRight":
        if (col < g.cols - 1) next = n + 1;
        break;
      case "ArrowLeft":
        if (col > 0) next = n - 1;
        break;
      case "ArrowDown":
        if (n + g.cols <= total) next = n + g.cols;
        break;
      case "ArrowUp":
        if (n - g.cols >= 1) next = n - g.cols;
        break;
      case "Home":
        next = n - col;
        break;
      case "End":
        next = n - col + g.cols - 1;
        break;
      case " ":
      case "Enter":
        event.preventDefault();
        toggle(data);
        return;
      default:
        return;
    }
    event.preventDefault();
    if (next !== n) focusCell(next);
  };

  const scrolls = layout.tap || zoom > 1;
  const rows = Array.from({ length: g.rows }, (_, row) => row);
  return (
    <div
      ref={wrapRef}
      data-scroll={scrolls ? "both" : undefined}
      className={`w-full min-w-0 overscroll-contain ${scrolls ? "max-h-[70dvh] overflow-auto rounded-r2 border border-line" : ""}`}
    >
      <svg
        ref={svgRef}
        role="grid"
        aria-label={label}
        aria-rowcount={g.rows}
        aria-colcount={g.cols}
        aria-readonly={!interactive || undefined}
        width={layout.width}
        height={layout.height}
        viewBox={`0 0 ${layout.pageW} ${layout.pageH}`}
        className={`block select-none ${interactive ? "touch-manipulation" : ""}`}
      >
        <StatePatterns id={patternId} />
        <rect width={layout.pageW} height={layout.pageH} className="fill-surface stroke-line-strong" strokeWidth={0.4} />
        {overlayPng && <image href={overlayPng} x="0" y="0" width={layout.pageW} height={layout.pageH} preserveAspectRatio="none" />}
        {rows.map((row) => (
          <g key={row} role="row" aria-rowindex={row + 1}>
            {Array.from({ length: g.cols }, (_, col) => {
              const n = row * g.cols + col + 1;
              const data = byNumber.get(n) ?? { cell: n, state: "free" as const };
              const rect = cellRect(g, n);
              const enabled = interactive && canToggle(data);
              return (
                <g
                  key={n}
                  role="gridcell"
                  data-cell={n}
                  aria-colindex={col + 1}
                  aria-label={cellLabel(data, t)}
                  aria-disabled={interactive && !enabled ? true : undefined}
                  tabIndex={n === Math.min(active, total) ? 0 : -1}
                  onFocus={() => {
                    setActive(n);
                    onInspect?.(n);
                  }}
                  onKeyDown={(e) => onKeyDown(e, n, data)}
                  onClick={() => toggle(data)}
                  className={`group/cell outline-none ${enabled ? "cursor-pointer" : ""}`}
                >
                  {/* One accessible name: the aria-label. A <title> child would be announced as a second description. */}
                  <g className={`${enabled ? "press [transform-box:fill-box] origin-center" : ""} `}>
                    <CellBody
                      state={data.state}
                      x={rect.x}
                      y={rect.y}
                      w={rect.w}
                      h={rect.h}
                      round={round}
                      radius={radius}
                      patternId={patternId}
                      number={showNumbers ? n : undefined}
                      numberMm={numberMm}
                      isId={data.isId}
                      hwMargin={data.hwMargin}
                      hoverable={enabled}
                      overlay={!!overlayPng}
                    />
                  </g>
                  {round ? (
                    <circle cx={rect.x + rect.w / 2} cy={rect.y + rect.h / 2} r={rect.w / 2 + ringMm} fill="none" strokeWidth={ringMm}
                      data-ring="1" className="stroke-transparent group-focus-visible/cell:stroke-link" pointerEvents="none" />
                  ) : (
                    <rect x={rect.x - ringMm / 2} y={rect.y - ringMm / 2} width={rect.w + ringMm} height={rect.h + ringMm}
                      rx={radius + ringMm / 2} fill="none" strokeWidth={ringMm}
                      data-ring="1" className="stroke-transparent group-focus-visible/cell:stroke-link" pointerEvents="none" />
                  )}
                  {/* The touch target is the pitch box: the label plus half the gap on each side. */}
                  <rect
                    data-hit="1"
                    x={rect.x + rect.w / 2 - g.pitch_x / 2}
                    y={rect.y + rect.h / 2 - g.pitch_y / 2}
                    width={g.pitch_x}
                    height={g.pitch_y}
                    className="fill-transparent"
                  />
                </g>
              );
            })}
          </g>
        ))}
      </svg>
    </div>
  );
}

/** The six states with their markers and, when given, how many cells are in each. */
export function SheetLegend({ counts }: { counts?: Partial<Record<GridCellState, number>> }) {
  const { i18n } = useLingui();
  const patternId = `hatch-${useId().replace(/[^a-zA-Z0-9]/g, "")}`;
  const t: Translate = (d) => i18n._(d);
  return (
    <ul className="m-0 flex list-none flex-wrap gap-x-4 gap-y-2 p-0 text-small">
      {CELL_STATES.map((state) => (
        <li key={state} className="flex items-center gap-2">
          <svg width="28" height="18" viewBox="0 0 14 9" aria-hidden="true" className="block shrink-0">
            <StatePatterns id={`${patternId}-${state}`} />
            <CellBody state={state} x={0.5} y={0.5} w={13} h={8} round={false} radius={1.2} patternId={`${patternId}-${state}`} />
          </svg>
          <span>{cellStateWord(state, t)}</span>
          {counts?.[state] !== undefined && <span className="font-bold tabular-nums">{counts[state]}</span>}
        </li>
      ))}
    </ul>
  );
}
