// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

interface Matchable {
  key: string;
  vendor: string | null;
  product_codes: string[];
  description: string | null;
  geometry: { label_w: number; label_h: number };
}

const isDigit = (ch: string | undefined) => ch !== undefined && ch >= "0" && ch <= "9";
const isSpace = (ch: string | undefined) => ch !== undefined && /\s/.test(ch);

/**
 * Lower case, accents removed, decimal comma as a dot, and "101,6 × 38,1" as "101.6x38.1".
 * `origin[i]` is the index (in code points) of the character of `text` that `folded[i]` stands for; folding drops
 * the spaces around the "x", so the two strings do not line up one to one.
 */
export function foldWithMap(text: string): { folded: string; origin: number[] } {
  const chars: string[] = [];
  const from: number[] = [];
  Array.from(text).forEach((ch, index) => {
    for (const piece of Array.from(ch.toLowerCase())) {
      chars.push(Array.from(piece.normalize("NFD").replace(/\p{M}/gu, ""))[0] ?? piece);
      from.push(index);
    }
  });
  const out: string[] = [];
  const origin: number[] = [];
  const emit = (ch: string, at: number) => {
    out.push(ch);
    origin.push(from[at]!);
  };
  for (let i = 0; i < chars.length; i++) {
    const ch = chars[i]!;
    if (isDigit(ch)) {
      // "6 × 3": a digit, spaces, an x, spaces and a digit again.
      let j = i + 1;
      while (isSpace(chars[j])) j++;
      if (chars[j] === "x" || chars[j] === "×") {
        const x = j;
        j++;
        while (isSpace(chars[j])) j++;
        if (isDigit(chars[j])) {
          emit(ch, i);
          emit("x", x);
          i = j - 1;
          continue;
        }
      }
    }
    // "101,6": a comma between two digits is a decimal comma.
    if (ch === "," && isDigit(out.at(-1)) && isDigit(chars[i + 1])) emit(".", i);
    else emit(ch, i);
  }
  return { folded: out.join(""), origin };
}

export function foldForSearch(text: string): string {
  return foldWithMap(text).folded;
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
