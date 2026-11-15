// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * T18: a popover that React Aria positions next to its trigger enters with opacity only, never with
 * the scaling `popin`. While it scales, React Aria measures (and scrolls the chosen option into view
 * from) a rect smaller than the layout, which is the cause of #292 (see SheetTypeCombobox). Dialogs are
 * centred, not positioned, and may keep `popin`.
 *
 * Why a source check and not a behaviour test: jsdom has no layout and no animation, so the wrong rect
 * cannot be observed there; the e2e suite (short-viewport.spec.ts) observes it per screen, not for every
 * popover. What it cannot tell apart: a `<Popover` named in a comment or string, or a popover whose class
 * is built elsewhere. It reports file and line.
 */
const SRC = join(__dirname);

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return name === "i18n" ? [] : sources(path);
    return /\.tsx$/.test(name) && !/\.test\.tsx$/.test(name) ? [path] : [];
  });
}

describe("popover motion", () => {
  it("no positioned popover scales on entry", () => {
    const hits: string[] = [];
    for (const file of sources(SRC)) {
      readFileSync(file, "utf8")
        .split("\n")
        .forEach((line, i) => {
          if (/<Popover\b/.test(line) && /animate-\[popin/.test(line)) hits.push(`${relative(SRC, file)}:${i + 1}`);
        });
    }
    expect(hits, hits.join("\n")).toEqual([]);
  });
});
