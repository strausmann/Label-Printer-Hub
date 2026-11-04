import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

/** Minimal .po reader: returns msgid -> msgstr for non-obsolete, non-header entries. */
function readPo(locale: string): Map<string, string> {
  const text = readFileSync(resolve(__dirname, "locales", locale, "messages.po"), "utf8");
  const entries = new Map<string, string>();
  let id: string | null = null;
  let str: string | null = null;
  let target: "id" | "str" | null = null;
  const unquote = (s: string) => JSON.parse(s) as string;
  const flush = () => {
    if (id !== null && id !== "") entries.set(id, str ?? "");
    id = null;
    str = null;
    target = null;
  };
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (line.startsWith("#~")) continue; // obsolete
    if (line.startsWith("msgid ")) {
      flush();
      id = unquote(line.slice(6));
      target = "id";
    } else if (line.startsWith("msgstr ")) {
      str = unquote(line.slice(7));
      target = "str";
    } else if (line.startsWith('"')) {
      if (target === "id") id += unquote(line);
      else if (target === "str") str += unquote(line);
    } else if (line === "") {
      flush();
    }
  }
  flush();
  return entries;
}

describe("message catalogues", () => {
  it("de catalogue has a translation for every en message id", () => {
    const en = readPo("en");
    const de = readPo("de");
    expect(en.size).toBeGreaterThan(0);
    const missing = [...en.keys()].filter((id) => !de.get(id));
    expect(missing).toEqual([]);
  });

  it("de has no ids that en lacks", () => {
    const en = readPo("en");
    const extra = [...readPo("de").keys()].filter((id) => !en.has(id));
    expect(extra).toEqual([]);
  });
});
