// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { CrossingFigure } from "./CrossingFigure";
import { SheetCrossingsFigure } from "./SheetCrossingsFigure";

// The website shows the same two drawings as the app. The React components are the source; the files
// under website/src/assets/guide/ are rendered from them (`pnpm guide:svg`) and this test fails when the
// two differ. They are rendered without a title, so without role and aria-label: the Astro page sets the
// localised ones. The sheet figure is the one of a 4 × 12 sheet.

// The header the generated files carry; REUSE would read these two lines as the header of this test file.
// REUSE-IgnoreStart
const SPDX = [
  "<!-- SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors -->",
  "<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->",
].join("\n");
// REUSE-IgnoreEnd

const dir = resolve(__dirname, "../../../../../website/src/assets/guide");

const FILES = [
  { name: "crossing.svg", svg: () => renderToStaticMarkup(<CrossingFigure idPrefix="guide-crossing" />) },
  { name: "sheet-crossings.svg", svg: () => renderToStaticMarkup(<SheetCrossingsFigure cols={4} rows={12} idPrefix="guide-sheet" />) },
];

const content = (svg: string) => `${SPDX}\n${svg}\n`;

describe("the website figures", () => {
  it("the website figures equal the rendered components", () => {
    for (const file of FILES) {
      const path = resolve(dir, file.name);
      const want = content(file.svg());
      if (process.env["GUIDE_SVG_WRITE"] === "1") {
        writeFileSync(path, want);
        continue;
      }
      expect(readFileSync(path, "utf8"), `${file.name} differs from its component; run pnpm guide:svg`).toBe(want);
    }
  });

  it("are plain SVG roots with a namespace, no XML prolog and no accessible name", () => {
    for (const file of FILES) {
      const svg = file.svg();
      expect(svg.startsWith('<svg xmlns="http://www.w3.org/2000/svg"')).toBe(true);
      expect(svg).not.toContain("<?xml");
      expect(svg).not.toMatch(/role=|aria-label=/);
    }
  });
});
