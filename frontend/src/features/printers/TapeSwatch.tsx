import { useLingui } from "@lingui/react/macro";
import { useColourNames, type TapeColour } from "./model";

const SWATCH: Record<TapeColour, string> = {
  white: "bg-tape-white",
  yellow: "bg-tape-yellow",
  green: "bg-tape-green",
  blue: "bg-tape-blue",
  red: "bg-tape-red",
  black: "bg-tape-black",
  // Clear tape has no colour of its own: an empty, dashed swatch reads as "see-through" in both themes.
  clear: "bg-tape-clear border-dashed",
};

/** The material colour as a small square. Never state, so it is hidden from assistive technology and always sits beside the colour's name. */
export function ColourSwatch({ colour }: { colour: TapeColour }) {
  return <span aria-hidden="true" className={`size-4 shrink-0 rounded-r1 border border-line-strong ${SWATCH[colour]}`} />;
}

/**
 * The loaded tape: width, and the colour when the operator gave one. The printer reports no colour,
 * so without one there is no colour line at all (never "not reported": that would read as a fault).
 */
export function TapeSwatch({
  widthMm,
  colour,
  probed = true,
}: {
  widthMm: number | null | undefined;
  colour: TapeColour | null | undefined;
  probed?: boolean;
}) {
  const { t } = useLingui();
  const names = useColourNames();
  const width = widthMm ?? null;
  // Before the first probe "no tape" would be a guess; say that nothing is known yet.
  if (width === null && !colour) return <span className="text-ink-2">{probed ? t`No tape loaded` : t`Tape not known yet`}</span>;
  return (
    <span className="inline-flex flex-wrap items-center gap-x-3 gap-y-1">
      {width !== null && <span className="font-bold">{t`${width} mm`}</span>}
      {colour && (
        <span className="inline-flex min-w-0 items-center gap-2">
          <ColourSwatch colour={colour} />
          <span className="[overflow-wrap:anywhere]">{names[colour]}</span>
        </span>
      )}
    </span>
  );
}
