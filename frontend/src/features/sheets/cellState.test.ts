import { describe, expect, it } from "vitest";
import { i18n } from "@lingui/core";
import {
  asymmetryHints,
  cellLabel,
  cellRect,
  gridLayout,
  remainingMargins,
  type GeometryMm,
  type GridCell,
  type Translate,
} from "./cellState";
import { initI18n } from "../../i18n";

const L4731REV: GeometryMm = {
  page_size: "A4", page_w: 210, page_h: 297, label_w: 25.4, label_h: 10, cols: 7, rows: 27,
  pitch_x: 27.9, pitch_y: 10, margin_top: 13.5, margin_left: 8.6, corner_radius: 1.5, shape: "rectangle",
};
const L4736REV: GeometryMm = {
  page_size: "A4", page_w: 210, page_h: 297, label_w: 45.7, label_h: 21.2, cols: 4, rows: 12,
  pitch_x: 48.2, pitch_y: 21.2, margin_top: 21.3, margin_left: 9.85, corner_radius: null, shape: "rectangle",
};

describe("gridLayout", () => {
  it("view fits the container width at the true aspect ratio", () => {
    const l = gridLayout(L4731REV, 360, "view");
    expect(l.tap).toBe(false);
    expect(l.width).toBeLessThanOrEqual(360);
    expect(l.height / l.width).toBeCloseTo(297 / 210, 3);
    // the touchable cell (label plus half the gap each side = the pitch box) is at least 44 px wide
    expect(L4731REV.pitch_x * l.scale).toBeGreaterThanOrEqual(44);
  });

  it("view zoom 2 doubles the size", () => {
    expect(gridLayout(L4731REV, 360, "view", 2).width).toBeCloseTo(720, 5);
  });

  it("view is capped on wide containers", () => {
    expect(gridLayout(L4731REV, 1600, "view").width).toBeLessThanOrEqual(760);
  });

  it.each(["select", "skip"] as const)("%s below 640 px zooms so every hit box is 44 x 44 px", (mode) => {
    for (const g of [L4731REV, L4736REV]) {
      const l = gridLayout(g, 360, mode);
      expect(l.tap).toBe(true);
      expect(g.pitch_x * l.scale).toBeGreaterThanOrEqual(44 - 1e-9);
      expect(g.pitch_y * l.scale).toBeGreaterThanOrEqual(44 - 1e-9);
      expect(l.width).toBeGreaterThan(360); // the scroll container overflows, the page does not
    }
  });

  it("select at 640 px and above is the plain fitted view", () => {
    expect(gridLayout(L4731REV, 640, "select").tap).toBe(false);
  });

  it("falls back to the page_size constants when page_w/page_h are missing", () => {
    const g = { ...L4731REV, page_w: null, page_h: undefined, page_size: "Letter" as const };
    const l = gridLayout(g, 400, "view");
    expect(l.pageW).toBeCloseTo(215.9, 5);
    expect(l.pageH).toBeCloseTo(279.4, 5);
    expect(Number.isFinite(l.width)).toBe(true);
  });
});

describe("geometry helpers", () => {
  it("cellRect is row-major and 1-based", () => {
    expect(cellRect(L4731REV, 1)).toMatchObject({ x: 8.6, y: 13.5, row: 0, col: 0 });
    expect(cellRect(L4731REV, 8)).toMatchObject({ x: 8.6, y: 23.5, row: 1, col: 0 });
    expect(cellRect(L4731REV, 6)).toMatchObject({ col: 5, row: 0 });
  });

  it("remaining margins are computed right and bottom", () => {
    const m = remainingMargins(L4731REV);
    expect(m.right).toBeCloseTo(8.6, 5);
    expect(m.bottom).toBeCloseTo(13.5, 5);
  });

  it("asymmetry uses the server's 0.5 mm threshold", () => {
    expect(asymmetryHints(L4731REV)).toEqual([]);
    expect(asymmetryHints({ ...L4731REV, margin_left: 5 })).toEqual(["margins_asymmetric_x"]);
    expect(asymmetryHints({ ...L4731REV, margin_top: 5, margin_left: 5 })).toEqual([
      "margins_asymmetric_x", "margins_asymmetric_y",
    ]);
    // exactly 0.5 mm apart is not flagged
    expect(asymmetryHints({ ...L4731REV, margin_left: 8.35 })).toEqual([]);
  });
});

describe("cellLabel", () => {
  const t: Translate = (d) => i18n._(d);
  it("reads like 'Cell 5, used, Grocy · flour 1 kg'", async () => {
    await initI18n("en");
    expect(cellLabel({ cell: 5, state: "used", purpose: "Grocy · flour 1 kg" }, t)).toBe(
      "Cell 5, used, Grocy · flour 1 kg",
    );
  });

  it("names every state and adds the flags", async () => {
    await initI18n("en");
    const base: GridCell = { cell: 2, state: "free" };
    expect(cellLabel(base, t)).toBe("Cell 2, free");
    expect(cellLabel({ ...base, state: "reserved" }, t)).toBe("Cell 2, reserved");
    expect(cellLabel({ ...base, state: "unconfirmed" }, t)).toBe("Cell 2, unconfirmed");
    expect(cellLabel({ ...base, state: "new" }, t)).toBe("Cell 2, new");
    expect(cellLabel({ ...base, state: "skipped" }, t)).toBe("Cell 2, skipped");
    expect(cellLabel({ cell: 3, state: "new", isId: true, hwMargin: true, truncated: true }, t)).toBe(
      "Cell 3, new, sheet ID, in the printer's unprintable margin, text shortened",
    );
  });

  it("is German in German", async () => {
    await initI18n("de");
    expect(cellLabel({ cell: 5, state: "used", purpose: "Mehl" }, t)).toBe("Zelle 5, belegt, Mehl");
    await initI18n("en");
  });
});
