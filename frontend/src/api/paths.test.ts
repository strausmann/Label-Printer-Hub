import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Source guard: the frontend must call the API under /api/v1 only.
 *
 * Limits: this is a text scan. It cannot see a path assembled without the
 * "/api/" literal. No behaviour test can cover this class, because there are
 * about 61 non-test call sites (apiFetch, links, EventSource) and no central
 * URL builder to hook into.
 */
const ROOT = resolve(__dirname, "../..");
const SELF = resolve(__filename);
const UNVERSIONED = /(?<![.\w])\/api\/(?!v1\/)/;

function walk(dir: string, out: string[]): string[] {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) {
      walk(full, out);
    } else if (/\.(ts|tsx)$/.test(name)) {
      out.push(full);
    }
  }
  return out;
}

describe("api paths", () => {
  it("no unversioned API path in the frontend source", () => {
    const files = [...walk(join(ROOT, "src"), []), ...walk(join(ROOT, "e2e"), [])].filter(
      (f) => !f.endsWith("schema.gen.ts") && resolve(f) !== SELF,
    );
    expect(files.length).toBeGreaterThan(50);
    const offenders: string[] = [];
    for (const file of files) {
      readFileSync(file, "utf8")
        .split("\n")
        .forEach((line, i) => {
          if (UNVERSIONED.test(line)) offenders.push(`${relative(ROOT, file)}:${i + 1}: ${line.trim()}`);
        });
    }
    expect(offenders).toEqual([]);
  });
});
