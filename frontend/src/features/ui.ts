/** Shared class strings for the feature pages (tokens only; focus ring comes from react-aria's data attribute). */
const FOCUS =
  "data-[focus-visible]:outline-3 data-[focus-visible]:outline-offset-2 data-[focus-visible]:outline-link";

export const SECONDARY_BUTTON =
  `press inline-flex h-11 items-center justify-center rounded-r2 border border-line-strong bg-surface px-4 text-small font-bold text-ink transition-colors duration-150 hover:bg-sunken data-[disabled]:opacity-60 ${FOCUS}`;

export const PRIMARY_BUTTON =
  `press inline-flex h-11 items-center justify-center rounded-r2 bg-accent px-5 font-bold text-accent-ink transition-colors duration-150 hover:bg-amber-600 hover:text-white data-[disabled]:opacity-60 ${FOCUS}`;

export const PANEL = "rounded-r3 border border-line bg-surface p-4";
export const SECTION_HEADING = "text-section font-bold";
