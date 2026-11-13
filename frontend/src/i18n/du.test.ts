import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * The German UI addresses the reader as "du" (#268). These tests scan the
 * catalogue text. Limit: a text scan cannot judge address form. It finds the
 * formal pronouns and checks that placeholders survived; it cannot tell a
 * formal imperative ("Geben Sie ...") apart from a third person plural unless
 * the pronoun is a word of its own. Imperatives are caught through "Sie".
 */

interface PoEntry {
  msgid: string;
  msgstr: string;
  /** 1-based line of the msgstr keyword. */
  line: number;
}

function readPoEntries(locale: string): PoEntry[] {
  const text = readFileSync(resolve(__dirname, "locales", locale, "messages.po"), "utf8");
  const entries: PoEntry[] = [];
  let id: string | null = null;
  let str: string | null = null;
  let strLine = 0;
  let target: "id" | "str" | null = null;
  const unquote = (s: string) => JSON.parse(s) as string;
  const flush = () => {
    if (id !== null && id !== "") entries.push({ msgid: id, msgstr: str ?? "", line: strLine });
    id = null;
    str = null;
    target = null;
  };
  text.split("\n").forEach((raw, index) => {
    const line = raw.trim();
    if (line.startsWith("#~")) return; // obsolete
    if (line.startsWith("msgid ")) {
      flush();
      id = unquote(line.slice(6));
      target = "id";
    } else if (line.startsWith("msgstr ")) {
      str = unquote(line.slice(7));
      strLine = index + 1;
      target = "str";
    } else if (line.startsWith('"')) {
      if (target === "id") id += unquote(line);
      else if (target === "str") str += unquote(line);
    } else if (line === "") {
      flush();
    }
  });
  flush();
  return entries;
}

/**
 * Entries where "Sie" is the third person (apps, keys, printers, records),
 * not an address of the reader. Keyed by msgid. A new exception needs the same
 * justification in review.
 */
const THIRD_PERSON_EXCEPTIONS: Record<string, string> = {
  "Other apps that print through this hub. They are recognised by the name of their API key.":
    "third person, not an address: 'Sie' = the other apps",
  "Sign-in through a reverse proxy is configured. It is set by the container and cannot be changed here.":
    "third person, not an address: 'Sie' = the sign-in",
  "Tap the free labels that are gone. They are written down as marked by hand.":
    "third person, not an address: 'Sie' = the labels",
  "The last 200 records of level warning or higher, newest first. They are kept in memory and start over with the container.":
    "third person, not an address: 'Sie' = the records",
  "The server refused the file: it is larger than 64 KB.":
    "third person, not an address: 'Sie' = the file",
  "These fitted values are outside the allowed range: {outOfRangeList}. They are not filled in. More than that is a fault of the printer, not something to correct.":
    "third person, not an address: 'Sie' = the values",
};

// Word boundaries by Unicode letters: JavaScript's `\b` counts only ASCII letters as word characters, so
// next to "ä", "ö", "ü" or "ß" it saw a word edge inside a word ("Sieä", "üSie").
const FORMAL = /(?<![\p{L}\p{N}])(Sie|Ihr|Ihre|Ihren|Ihrem|Ihrer|Ihnen)(?![\p{L}\p{N}])/u;

describe("German catalogue address form", () => {
  it("finds the formal pronoun as a word, also next to umlauts", () => {
    expect(FORMAL.test("Wählen Sie den Drucker")).toBe(true);
    expect(FORMAL.test("Ihnen.")).toBe(true);
    // Not a pronoun: a word that only contains the letters.
    expect(FORMAL.test("Ihrzeit")).toBe(false);
    expect(FORMAL.test("Sieb")).toBe(false);
    expect(FORMAL.test("üSie")).toBe(false);
    expect(FORMAL.test("Sieä")).toBe(false);
  });

  it("no formal address in the German catalogue", () => {
    const entries = readPoEntries("de");
    const hits = entries
      .filter((e) => FORMAL.test(e.msgstr) && !(e.msgid in THIRD_PERSON_EXCEPTIONS))
      .map((e) => `line ${e.line}: ${JSON.stringify(e.msgid)} -> ${JSON.stringify(e.msgstr)}`);
    expect(hits, hits.join("\n")).toEqual([]);
  });

  it("every exception still exists and still contains a formal pronoun", () => {
    const byId = new Map(readPoEntries("de").map((e) => [e.msgid, e.msgstr]));
    for (const id of Object.keys(THIRD_PERSON_EXCEPTIONS)) {
      expect(byId.has(id), `stale exception: ${id}`).toBe(true);
      expect(FORMAL.test(byId.get(id) ?? ""), `exception no longer needed: ${id}`).toBe(true);
    }
  });
});

/**
 * Names of the ICU arguments of a message: top level and nested; `#` and branch texts are not arguments.
 * It does not read ICU apostrophe quoting (`'{'` as a literal brace); no catalogue message uses it, which
 * the test "uses no apostrophe-quoted braces" below holds true.
 */
function icuArgumentNames(message: string): Set<string> {
  const names = new Set<string>();
  const closing = (open: number, end: number): number => {
    let depth = 0;
    for (let k = open; k < end; k++) {
      if (message[k] === "{") depth++;
      else if (message[k] === "}" && --depth === 0) return k;
    }
    return end;
  };
  const scan = (start: number, end: number): void => {
    let i = start;
    while (i < end) {
      if (message[i] !== "{") {
        i++;
        continue;
      }
      const close = closing(i, end);
      const inner = message.slice(i + 1, close);
      const m = /^\s*([^\s,{}]+)\s*(?:,\s*(plural|select|selectordinal)\s*,)?/.exec(inner);
      if (m) {
        names.add(m[1] as string);
        if (m[2]) {
          // Body is `key {branch text} key {branch text}`: scan inside each branch group.
          let k = i + 1 + m[0].length;
          while (k < close) {
            if (message[k] === "{") {
              const branchClose = closing(k, close + 1);
              scan(k + 1, branchClose);
              k = branchClose + 1;
            } else {
              k++;
            }
          }
        }
      }
      i = close + 1;
    }
  };
  scan(0, message.length);
  return names;
}

describe("ICU argument parser", () => {
  it("reads plain, plural and nested arguments", () => {
    expect([...icuArgumentNames("{0, plural, one {# cell} other {# cells}}")]).toEqual(["0"]);
    expect([...icuArgumentNames("Hello {name}, {count}")].sort()).toEqual(["count", "name"]);
    expect(
      [...icuArgumentNames("{n, plural, one {{who} has # cell} other {# cells}}")].sort(),
    ).toEqual(["n", "who"]);
    expect([...icuArgumentNames("{g, select, a {x} other {y}}")]).toEqual(["g"]);
    expect([...icuArgumentNames("no arguments")]).toEqual([]);
  });

  it("uses no apostrophe-quoted braces, which it would read as arguments", () => {
    const quoted = (["en", "de"] as const)
      .flatMap((locale) => readPoEntries(locale).map((e) => ({ locale, ...e })))
      .filter((e) => /'[{}]/.test(e.msgid) || /'[{}]/.test(e.msgstr))
      .map((e) => `${e.locale} line ${e.line}: ${JSON.stringify(e.msgid)}`);
    expect(quoted, quoted.join("\n")).toEqual([]);
  });
});

describe("German placeholders", () => {
  it("placeholders survive the du rewrite", () => {
    const problems: string[] = [];
    for (const e of readPoEntries("de")) {
      if (e.msgstr === "") continue;
      const want = [...icuArgumentNames(e.msgid)].sort();
      const got = [...icuArgumentNames(e.msgstr)].sort();
      if (JSON.stringify(want) !== JSON.stringify(got)) {
        problems.push(`line ${e.line}: ${JSON.stringify(e.msgid)} want ${want} got ${got}`);
      }
    }
    expect(problems, problems.join("\n")).toEqual([]);
  });
});
