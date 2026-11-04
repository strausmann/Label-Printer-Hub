import { useLingui } from "@lingui/react/macro";
import { parseTape, useColourNames, type TapeColour } from "./model";

const SWATCH: Record<TapeColour, string> = {
  white: "bg-tape-white",
  yellow: "bg-tape-yellow",
  green: "bg-tape-green",
  blue: "bg-tape-blue",
  red: "bg-tape-red",
};

/**
 * The loaded tape: width and colour. The swatch is material, never state, so it always
 * sits next to the colour's name and is hidden from assistive technology.
 */
export function TapeSwatch({ tapeLoaded, probed = true }: { tapeLoaded: string | null | undefined; probed?: boolean }) {
  const { t } = useLingui();
  const names = useColourNames();
  const tape = parseTape(tapeLoaded);
  // Before the first probe "no tape" would be a guess; say that nothing is known yet.
  if (!tape) return <span className="text-ink-2">{probed ? t`No tape loaded` : t`Tape not known yet`}</span>;
  const colourText = tape.colour ? names[tape.colour] : tape.colourName ? capitalise(tape.colourName) : null;
  return (
    <span className="inline-flex flex-wrap items-center gap-x-3 gap-y-1">
      {tape.widthMm !== null && <span className="font-bold">{t`${tape.widthMm} mm`}</span>}
      {tape.colour ? (
        <span className="inline-flex items-center gap-2">
          <span aria-hidden="true" className={`size-4 shrink-0 rounded-r1 border border-line-strong ${SWATCH[tape.colour]}`} />
          <span>{colourText}</span>
        </span>
      ) : colourText ? (
        <span>{colourText}</span>
      ) : (
        <span className="text-ink-2">{t`Colour not reported`}</span>
      )}
    </span>
  );
}

function capitalise(word: string): string {
  return word.charAt(0).toUpperCase() + word.slice(1);
}
