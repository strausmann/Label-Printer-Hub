// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { INFO, renderApp, SIGNED_IN } from "../../test-utils";
import { mockApi } from "../test-api";
import { open, P, resetBetweenTests, routes } from "./CalibrationPage.kit";
import { miniScaleTicks } from "./CalibrationSchematic";

resetBetweenTests();

/** The numbers of the printed page, read from the file that draws it. */
function backendScale(): Record<string, number> {
  const source = readFileSync(resolve(process.cwd(), "../backend/app/calibration/scale.py"), "utf8");
  const found: Record<string, number> = {};
  for (const m of source.matchAll(/^([A-Z_]+_MM) = ([0-9.]+)$/gm)) found[m[1]!] = Number(m[2]);
  return found;
}

describe("the schematic is drawn to the scale of the print (#348)", () => {
  it("the app's copy of the scale in the test fixture is the backend's", () => {
    const b = backendScale();
    expect(INFO.calibration_scale).toEqual({
      half_mm: b.HALF_MM,
      step_mm: b.STEP_MM,
      line_mm: b.LINE_MM,
      tick_half_mm: b.TICK_HALF_MM,
      tick_whole_mm: b.TICK_WHOLE_MM,
      tick_centre_mm: b.TICK_CENTRE_MM,
    });
  });

  it("lays out nine ticks, the whole millimetres longer, the centre the longest, the white between them above the floor", () => {
    const b = backendScale();
    const ticks = miniScaleTicks(INFO.calibration_scale);
    expect(ticks.map((t) => t.offset)).toEqual([-2, -1.5, -1, -0.5, 0, 0.5, 1, 1.5, 2]);
    expect(ticks.map((t) => t.length)).toEqual([1.4, 0.8, 1.4, 0.8, 2, 0.8, 1.4, 0.8, 1.4]);
    const pitch = ticks[1]!.offset - ticks[0]!.offset;
    expect(pitch - INFO.calibration_scale.line_mm).toBeGreaterThanOrEqual(b.MIN_GAP_MM! - 1e-9);
  });

  it("draws the crossing with those spacings, lengths and stroke, magnified five times", async () => {
    await open();
    const section = await screen.findByRole("region", { name: "Gap crossing S2 · Z6" });
    const ticks = [...section.querySelectorAll("g[data-tick]")];
    expect(ticks).toHaveLength(9);
    const m = 5;
    const down = ticks.map((g) => g.querySelector("line")!); // the tick of the scale along x: vertical
    expect(down.map((l) => Number(l.getAttribute("x1")) / m)).toEqual([-2, -1.5, -1, -0.5, 0, 0.5, 1, 1.5, 2]);
    const lengths = down.map((l) => (Number(l.getAttribute("y2")) - Number(l.getAttribute("y1"))) / m);
    expect(lengths.map((v) => Math.round(v * 100) / 100)).toEqual([1.4, 0.8, 1.4, 0.8, 2, 0.8, 1.4, 0.8, 1.4]);
    expect(Number(ticks[0]!.getAttribute("stroke-width")) / m).toBeCloseTo(INFO.calibration_scale.line_mm);
    // The legend of the page drawing names the same step.
    expect(await screen.findByText("At every crossing sits a small scale: ±2 mm, a tick every 0.5 mm.")).toBeVisible();
  });

  it("draws no ticks, and says so only generally, until the scale is known", async () => {
    mockApi(routes());
    await renderApp({ path: `/calibration?printer=${P}&tray=main`, session: SIGNED_IN, info: { calibration_scale: undefined } });
    const section = await screen.findByRole("region", { name: "Gap crossing S2 · Z6" });
    expect(section.querySelectorAll("g[data-tick]")).toHaveLength(0);
    expect(await screen.findByText("At every crossing sits a small scale.")).toBeVisible();
  });
});
