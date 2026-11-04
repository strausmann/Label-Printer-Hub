import { createHash } from "node:crypto";
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

  it("pwa: the generated service worker never caches /api", () => {
    const sw = readFileSync(join(dist, "sw.js"), "utf8");
    // The only route is the navigation fallback, and it skips the API, docs and OpenAPI document.
    expect(sw.match(/registerRoute\(/g)).toHaveLength(1);
    expect(sw).toContain('createHandlerBoundToURL("/index.html")');
    for (const denied of ["/^\\/api\\//", "/^\\/docs(\\/|$)/", "/^\\/openapi\\.json$/", "/^\\/redoc(\\/|$)/"]) expect(sw).toContain(denied);
    // Nothing under /api is precached either.
    expect(sw).not.toMatch(/["']\/?api\//);
  });

  it("ships the code reader's WebAssembly from this origin, not a CDN", () => {
    expect(walk(dist, ".wasm").some((f) => /zxing_reader/.test(f))).toBe(true);
    const worker = walk(join(dist, "assets"), ".js").filter((f) => /decoder\.worker/.test(f));
    expect(worker).toHaveLength(1);
    // The library's default points at a CDN; our override must be what the worker uses.
    expect(readFileSync(worker[0]!, "utf8")).toMatch(/zxing_reader-[\w-]+\.wasm/);
  });

  it("csp: the one inline style the UI library injects is allowed by its hash, and nothing broader", () => {
    const main = walk(join(dist, "assets"), ".js").find((f) => /index-/.test(f))!;
    const code = readFileSync(main, "utf8");
    const at = code.indexOf("react-aria-pressable-style");
    expect(at, "react-aria no longer injects its pressable style; drop the hash from backend/app/web/spa.py").toBeGreaterThan(-1);
    // `t.textContent=`\n@layer { [${attr}] {...} }\n    `.trim()`: a template in the minified bundle.
    const quoted = /textContent=`(\s*@layer \{[^`]*)`\.trim\(\)/.exec(code);
    expect(quoted, "could not find the style text next to its id").not.toBeNull();
    const text = quoted![1]!.replace(/\$\{[^}]+\}/, "data-react-aria-pressable").trim();
    const hash = createHash("sha256").update(text).digest("base64");
    const csp = readFileSync(resolve(__dirname, "..", "..", "backend", "app", "web", "spa.py"), "utf8");
    expect(csp).toContain(`'sha256-${hash}'`);
    expect(csp).not.toContain("unsafe-inline");
  });
});
