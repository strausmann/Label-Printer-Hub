// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { contrastRatio, primitives, radii, tape, themes, type Semantic } from "./tokens";

const css = readFileSync(resolve(__dirname, "tokens.css"), "utf8");

/** Collect `--name: value;` declarations of the first block that starts with `selector`. */
function block(source: string, selector: string): Record<string, string> {
  const start = source.indexOf(selector);
  if (start < 0) throw new Error(`selector not found: ${selector}`);
  const open = source.indexOf("{", start);
  let depth = 0;
  let end = open;
  for (let i = open; i < source.length; i += 1) {
    if (source[i] === "{") depth += 1;
    if (source[i] === "}") depth -= 1;
    if (depth === 0) {
      end = i;
      break;
    }
  }
  const body = source.slice(open + 1, end);
  const out: Record<string, string> = {};
  for (const m of body.matchAll(/(--[a-z0-9-]+)\s*:\s*([^;]+);/g)) {
    out[m[1]!] = m[2]!.trim();
  }
  return out;
}

function resolveVars(decls: Record<string, string>, base: Record<string, string>): Record<string, string> {
  const all = { ...base, ...decls };
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(decls)) {
    const ref = /^var\((--[a-z0-9-]+)\)$/.exec(v);
    out[k] = ref ? all[ref[1]!]!.toUpperCase() : v.toUpperCase();
  }
  return out;
}

const roles: (keyof Semantic)[] = [
  "bg", "surface", "sunken", "line", "line-strong", "ink", "ink-2", "ink-3",
  "accent", "accent-ink", "accent-soft", "link", "ok", "warn", "bad",
];

describe("contrast", () => {
  it("computes the WCAG ratio for black on white", () => {
    expect(contrastRatio("#000000", "#FFFFFF")).toBeCloseTo(21, 5);
    expect(contrastRatio("#FFFFFF", "#FFFFFF")).toBeCloseTo(1, 5);
  });

  for (const theme of ["light", "dark"] as const) {
    it(`every text role meets WCAG AA on bg and surface in the ${theme} theme`, () => {
      const t = themes[theme];
      const failures: string[] = [];
      const check = (fg: keyof Semantic, bgRole: keyof Semantic, min: number) => {
        const ratio = contrastRatio(t[fg], t[bgRole]);
        if (ratio < min) failures.push(`${theme}: ${fg} ${t[fg]} on ${bgRole} ${t[bgRole]} = ${ratio.toFixed(2)} (< ${min})`);
      };
      for (const bgRole of ["bg", "surface"] as const) {
        check("ink", bgRole, 4.5);
        check("ink-2", bgRole, 4.5);
        check("link", bgRole, 4.5);
        // non-text state shapes (dot / diamond next to the word)
        check("ok", bgRole, 3);
        check("warn", bgRole, 3);
        check("bad", bgRole, 3);
      }
      check("ink-3", "bg", 4.5);
      check("accent-ink", "accent", 4.5);
      expect(failures).toEqual([]);
    });
  }

  it("ink-3 also reads on surface and sunken (D12)", () => {
    for (const theme of ["light", "dark"] as const) {
      const t = themes[theme];
      expect(contrastRatio(t["ink-3"], t.surface)).toBeGreaterThanOrEqual(4.5);
      expect(contrastRatio(t["ink-3"], t.sunken)).toBeGreaterThanOrEqual(4.5);
    }
  });

  it("uses ink-500 #6B655A for the light ink-3 (D12)", () => {
    expect(primitives["ink-500"]).toBe("#6B655A");
    expect(themes.light["ink-3"]).toBe("#6B655A");
  });
});

describe("tokens.css", () => {
  const prim = block(css, ":root");

  it("css custom properties equal tokens.ts", () => {
    for (const [name, value] of Object.entries(primitives)) {
      expect(prim[`--${name}`]?.toUpperCase(), `--${name}`).toBe(value.toUpperCase());
    }
    const light = resolveVars(prim, prim);
    for (const role of roles) {
      expect(light[`--${role}`], `light --${role}`).toBe(themes.light[role].toUpperCase());
    }
    for (const [name, value] of Object.entries(tape)) {
      expect(prim[`--tape-${name}`]?.toUpperCase(), `--tape-${name}`).toBe(value.toUpperCase());
    }
    for (const [name, value] of Object.entries(radii)) {
      expect(prim[`--r-${name}`], `--r-${name}`).toBe(value);
    }
  });

  it("dark values match under [data-theme=dark] and under the media query", () => {
    const explicit = resolveVars(block(css, '[data-theme="dark"]'), prim);
    const mediaStart = css.indexOf("@media (prefers-color-scheme: dark)");
    expect(mediaStart).toBeGreaterThan(-1);
    const media = resolveVars(block(css.slice(mediaStart), ":root:not([data-theme=\"light\"])"), prim);
    for (const role of roles) {
      expect(explicit[`--${role}`], `explicit --${role}`).toBe(themes.dark[role].toUpperCase());
      expect(media[`--${role}`], `media --${role}`).toBe(themes.dark[role].toUpperCase());
    }
  });

  it("defines no external urls", () => {
    expect(css).not.toMatch(/https?:\/\//);
  });
});
