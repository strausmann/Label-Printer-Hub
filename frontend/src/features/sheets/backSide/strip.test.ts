// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { describe, expect, it } from "vitest";
import { marginPossible, placeStrip } from "./strip";

const G3490 = { page_size: "A4", page_w: 210, page_h: 297, label_w: 70, label_h: 36, cols: 3, rows: 8, pitch_x: 70, pitch_y: 36, margin_top: 4.5, margin_left: 0, corner_radius: null, shape: "rectangle" } as const;
const G6121 = { ...G3490, label_w: 38.1, label_h: 21.18, cols: 5, rows: 13, pitch_x: 38.1, pitch_y: 21.18, margin_top: 10.8, margin_left: 9.9 } as const;

describe("code strip", () => {
  it("goes into the first strip that takes it, like the hub", () => {
    const ultragrip = [
      { x_mm: 33.5, y_mm: 22, w_mm: 22, h_mm: 253 },
      { x_mm: 154.5, y_mm: 22, w_mm: 22, h_mm: 253 },
    ];
    expect(placeStrip(ultragrip)).toEqual({ x_mm: 33.5, y_mm: 24, w_mm: 22, h_mm: 62 });
    expect(placeStrip([{ x_mm: 10, y_mm: 22, w_mm: 20, h_mm: 253 }, ultragrip[1]!])?.x_mm).toBe(154.5);
    expect(placeStrip([{ x_mm: 10, y_mm: 22, w_mm: 20, h_mm: 253 }])).toBeNull();
    expect(placeStrip([])).toEqual({ x_mm: 10, y_mm: 10, w_mm: 22, h_mm: 62 });
  });

  it("knows 3490 has no usable margin and 6121 has one", () => {
    expect(marginPossible(G3490)).toBe(false);
    expect(marginPossible(G6121)).toBe(true);
  });
});
