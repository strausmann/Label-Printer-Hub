import { useLingui } from "@lingui/react/macro";
import type { PrinterStatus } from "./api";

export type Marker = NonNullable<PrinterStatus["markers"]>[number];

/** Only a plain hex colour is ever written into a style; anything else gets no swatch fill. */
const HEX = /^#[0-9a-f]{6}$/i;

/** How full a supply is, in words: `empty` wins, then the percentage (with "low"), then "some remaining". */
export function useMarkerWords(): (marker: Marker) => string {
  const { t } = useLingui();
  return (marker) => {
    if (marker.empty) return t`empty`;
    if (marker.level_percent !== null) {
      const level = Math.round(marker.level_percent);
      return marker.low ? t`${level} %, low` : t`${level} %`;
    }
    if (marker.some_remaining) return t`some remaining`;
    return t`unknown`;
  };
}

/**
 * One supply of a page printer: a swatch of its colour, its name and its level in words.
 * The swatch is material, like the tape swatch: it is hidden from assistive technology and
 * never the only carrier of the state.
 */
export function MarkerSwatch({ marker }: { marker: Marker }) {
  const words = useMarkerWords()(marker);
  const fill = marker.color !== null && HEX.test(marker.color) ? marker.color : null;
  return (
    <span className="inline-flex min-w-0 items-start gap-2">
      <span
        data-swatch=""
        aria-hidden="true"
        className={`mt-1 size-4 shrink-0 rounded-r1 border ${fill ? "border-line-strong" : "border-dashed border-line-strong"}`}
        style={fill ? { backgroundColor: fill } : undefined}
      />
      <span className="min-w-0 [overflow-wrap:anywhere]">
        <span className="font-bold">{marker.name}</span>{" "}
        {/* A supply that needs attention reads in the full ink; the others stay secondary. */}
        <span className={`whitespace-nowrap ${marker.empty || marker.low ? "font-bold text-ink" : "text-ink-2"}`}>{words}</span>
      </span>
    </span>
  );
}
