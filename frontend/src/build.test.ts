import { createHash } from "node:crypto";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";

const dist = resolve(__dirname, "..", "dist");
const pkg = JSON.parse(readFileSync(resolve(__dirname, "..", "package.json"), "utf8")) as { name: string; dependencies: Record<string, string> };
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

  it("ships the licence notices the bundled fonts and the code reader require", () => {
    const read = (name: string) => readFileSync(join(dist, "licenses", name), "utf8");
    for (const [name, holder] of [
      ["atkinson-hyperlegible-OFL-1.1.txt", "Braille Institute of America"],
      ["atkinson-hyperlegible-mono-OFL-1.1.txt", "Atkinson Hyperlegible Mono Project Authors"],
    ] as const) {
      const text = read(name);
      expect(text).toContain(holder);
      expect(text).toContain("SIL OPEN FONT LICENSE Version 1.1");
    }
    const zxing = read("zxing-cpp-Apache-2.0.txt");
    expect(zxing).toContain("Nu-book Inc.");
    expect(zxing).toContain("Apache License");
    expect(zxing).toContain("END OF TERMS AND CONDITIONS");
  });

  it("pwa: the generated service worker never caches /api", () => {
    const sw = readFileSync(join(dist, "sw.js"), "utf8");
    // The only route is the navigation fallback, and it skips the API, docs and OpenAPI document.
    expect(sw.match(/registerRoute\(/g)).toHaveLength(1);
    expect(sw).toContain('createHandlerBoundToURL("/index.html")');
    for (const denied of ["/^\\/api\\//", "/^\\/docs(\\/|$)/", "/^\\/openapi\\.json$/"]) expect(sw).toContain(denied);
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

  it("ships the Scalar API reference bundle and its licence, kept out of the offline cache", () => {
    // The hub serves it at /docs/scalar.js (backend/app/web/api_docs.py); no CDN is involved.
    const bundle = join(dist, "scalar", "standalone.js");
    expect(existsSync(bundle), "dist/scalar/standalone.js is missing").toBe(true);
    expect(statSync(bundle).size).toBeGreaterThan(1_000_000);
    const licence = readFileSync(join(dist, "licenses", "scalar-api-reference-MIT.txt"), "utf8");
    expect(licence).toContain("MIT License");
    expect(licence).toContain("Scalar");
    // A 5 MB documentation viewer must not be precached for every installed app.
    expect(readFileSync(join(dist, "sw.js"), "utf8")).not.toContain("scalar/standalone.js");
  });

  it("ships a licence list of everything the web app ships, and none of the tools that build it", () => {
    const list = JSON.parse(readFileSync(join(dist, "licenses", "frontend.json"), "utf8")) as { name: string; licenseText: string | null }[];
    const byName = new Map(list.map((record) => [record.name, record]));
    for (const name of ["react", "react-dom", "@scalar/api-reference", "zxing-wasm", "workbox-precaching", "zxing-cpp"]) {
      expect(byName.has(name), `${name} is missing from frontend.json`).toBe(true);
      expect(byName.get(name)!.licenseText, `${name} has no licence text`).toBeTruthy();
    }
    // Every production dependency ships, including the two font packages whose CSS the bundler inlines.
    for (const name of Object.keys(pkg.dependencies)) expect(byName.has(name), `${name} is a dependency but missing from frontend.json`).toBe(true);
    // `yaml` is left out of this list on purpose: Scalar's standalone bundle contains it, so it ships.
    for (const tool of ["vite", "vitest", "typescript", "eslint", "@playwright/test", "rollup-license-plugin", pkg.name]) {
      expect(byName.has(tool), `${tool} must not be listed`).toBe(false);
    }
  });

  it("ships a CycloneDX document of the web bundle that names the project", () => {
    const bom = JSON.parse(readFileSync(join(dist, "frontend.cdx.json"), "utf8")) as {
      bomFormat: string;
      specVersion: string;
      metadata: { component: { name: string } };
      components: { purl: string }[];
    };
    expect(bom).toMatchObject({ bomFormat: "CycloneDX", specVersion: "1.6" });
    expect(bom.metadata.component.name).toBe(pkg.name);
    const purls = bom.components.map((component) => component.purl);
    expect(purls).toContain(`pkg:npm/react@${pkg.dependencies.react}`);
    expect(purls).toContain(`pkg:npm/%40scalar/api-reference@${pkg.dependencies["@scalar/api-reference"]}`);
    expect(purls.some((purl) => purl.startsWith("pkg:github/zxing-cpp/zxing-cpp@"))).toBe(true);
  });

  it("keeps the licence files out of the offline cache", () => {
    // pwa.config.ts precaches no json; a glob that did would put a 500 KB list into every installed app.
    const sw = readFileSync(join(dist, "sw.js"), "utf8");
    expect(sw).not.toContain("frontend.json");
    expect(sw).not.toContain("frontend.cdx.json");
  });

  it("csp: every inline style the bundle can inject is allowed by its hash, and nothing broader", () => {
    const csp = readFileSync(resolve(__dirname, "..", "..", "backend", "app", "web", "spa.py"), "utf8");
    expect(csp).not.toContain("unsafe-inline");
    // react-aria injects its styles at runtime (a touch-action rule, an iOS scroll lock). They live
    // in whichever chunk holds the component, so every script of the build is searched, not one.
    const scripts = walk(join(dist, "assets"), ".js").map((file) => ({ file, code: readFileSync(file, "utf8") }));
    const holders = scripts.filter(({ code }) => code.includes("react-aria-pressable-style"));
    expect(holders.length, "react-aria no longer injects its pressable style; drop its hash from backend/app/web/spa.py").toBeGreaterThan(0);

    const found: { file: string; text: string }[] = [];
    const unaccounted: string[] = [];
    for (const { file, code } of scripts) {
      for (const m of code.matchAll(/createElement\(`style`\)/g)) {
        const window = code.slice(m.index, m.index + 400);
        // `x.textContent=`...`` (maybe followed by .trim()): a template in the minified bundle.
        const quoted = /textContent=`([^`]*)`(\.trim\(\))?/.exec(window);
        if (quoted) {
          // `${name}` is a constant of the bundle (the attribute the rule targets): look its text up.
          const filled = quoted[1]!.replace(/\$\{(\w+)\}/g, (_all, name: string) => {
            const value = new RegExp(`\\b${name}=\`([^\`]*)\``).exec(code);
            expect(value, `constant ${name} used in an inline style could not be resolved`).not.toBeNull();
            return value![1]!;
          });
          found.push({ file, text: quoted[2] ? filled.trim() : filled });
        } else if (!/data-precedence/.test(code.slice(Math.max(0, m.index - 300), m.index + 100))) {
          // React DOM's own `<style precedence>` hoisting; the app renders none. Anything else is unknown.
          unaccounted.push(`${file}@${m.index}`);
        }
      }
    }
    expect(unaccounted, "a style element is created without a visible text: add a hash or remove it").toEqual([]);
    expect(found.length, "react-aria's two inline styles were expected").toBeGreaterThanOrEqual(2);
    const missing = found
      .map(({ file, text }) => ({ file, text, hash: createHash("sha256").update(text).digest("base64") }))
      .filter(({ hash }) => !csp.includes(`'sha256-${hash}'`))
      .map(({ file, text, hash }) => `${file}: sha256-${hash} for ${JSON.stringify(text)}`);
    expect(missing, "inline style without a CSP hash in backend/app/web/spa.py").toEqual([]);
  });
});
