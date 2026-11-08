/** The address of `/sheets`: the filters of the list. Everything that is not set means "the default". */
export interface SheetsSearch {
  /** Key of a sheet type. */
  type?: string | undefined;
  /** A piece of a sheet code. */
  q?: string | undefined;
  /** Show the sheets that are used up (hidden by default). */
  full?: true | undefined;
  /** Show the discarded sheets (hidden by default). */
  discarded?: true | undefined;
}

// The router parses `?q=123` as the number 123, so text arrives as a string or a number.
const text = (value: unknown): string | undefined => {
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return typeof value === "string" && value.trim() !== "" ? value.trim() : undefined;
};
const flag = (value: unknown): true | undefined => (value === true || value === "true" || value === 1 ? true : undefined);

/** Every key stays in the result even when rejected: the router merges it over the raw query string. */
export function parseSheetsSearch(search: Record<string, unknown>): SheetsSearch {
  return { type: text(search.type), q: text(search.q), full: flag(search.full), discarded: flag(search.discarded) };
}
