interface Matchable {
  key: string;
  vendor: string | null;
  product_codes: string[];
  description: string | null;
  geometry: { label_w: number; label_h: number };
}

/** Lower case, accents removed, decimal comma as a dot, and "101,6 × 38,1" as "101.6x38.1". Characters keep their count. */
export function foldForSearch(text: string): string {
  return Array.from(text.toLowerCase())
    .map((ch) => Array.from(ch.normalize("NFD").replace(/\p{M}/gu, ""))[0] ?? ch)
    .join("")
    .replace(/(\d)\s*[x×]\s*(?=\d)/g, "$1x")
    .replace(/(\d),(?=\d)/g, "$1.");
}

const mm = (value: number) => String(Math.round(value * 100) / 100);

/** The text a query is searched in: key, vendor, product codes, description and the label size. */
function haystack(type: Matchable): string {
  const size = `${mm(type.geometry.label_w)}x${mm(type.geometry.label_h)}`;
  return foldForSearch([type.key, type.vendor ?? "", ...type.product_codes, type.description ?? "", size].join(" "));
}

/**
 * Whether a sheet type answers a search. Every word of the query has to be found; case and accents do not matter.
 * The label size is found in the spellings `101,6 × 38,1`, `101.6x38.1` and `101,6x38,1`.
 */
export function matchSheetType(type: Matchable, query: string): boolean {
  const words = foldForSearch(query.trim()).split(/\s+/).filter(Boolean);
  if (words.length === 0) return true;
  const text = haystack(type);
  return words.every((word) => text.includes(word));
}
