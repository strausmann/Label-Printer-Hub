import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";

const dist = resolve(__dirname, "..", "dist");
// CI runs this file after `pnpm build` with REQUIRE_DIST=1 so a missing build fails instead of skipping.
const required = process.env.REQUIRE_DIST === "1";

function walk(dir: string, ext: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    return statSync(p).isDirectory() ? walk(p, ext) : p.endsWith(ext) ? [p] : [];
  });
}

describe.skipIf(!required && !existsSync(dist))("built output", () => {
  it("test_no_external_font_urls", () => {
    expect(existsSync(dist), "run `pnpm build` first").toBe(true);
    const files = walk(dist, ".css");
    expect(files.length).toBeGreaterThan(0);
    const offenders: string[] = [];
    for (const file of files) {
      const css = readFileSync(file, "utf8");
      for (const m of css.matchAll(/url\(\s*['"]?(https?:)?\/\/[^)]*\)/gi)) offenders.push(`${file}: ${m[0]}`);
      for (const m of css.matchAll(/@import\s+(url\()?\s*['"]?(https?:)?\/\//gi)) offenders.push(`${file}: ${m[0]}`);
    }
    expect(offenders).toEqual([]);
  });

  it("ships the self-hosted font files", () => {
    const fonts = walk(dist, ".woff2");
    expect(fonts.some((f) => /atkinson-hyperlegible-mono/.test(f))).toBe(true);
    expect(fonts.some((f) => /atkinson-hyperlegible-latin/.test(f) && !/mono/.test(f))).toBe(true);
  });
});
