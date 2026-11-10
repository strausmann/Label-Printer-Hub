import { describe, expect, it } from "vitest";
import { hasLayoutChoice, layoutDefaultFor, tapeMmOfStatus, toOptions } from "./ql";

describe("QL layout helpers", () => {
  it("uses the stored default per width and the tape default for the rest", () => {
    expect(layoutDefaultFor({ "62": { orientation: "along", preset: null } }, 62)).toEqual({ orientation: "along", preset: "compact" });
    expect(layoutDefaultFor({ "62": { orientation: null, preset: "standard" } }, 62)).toEqual({ orientation: "across", preset: "standard" });
    expect(layoutDefaultFor({}, 62)).toEqual({ orientation: "across", preset: "compact" });
    expect(layoutDefaultFor(undefined, 62)).toEqual({ orientation: "across", preset: "compact" });
  });

  it("sends the preset for across only", () => {
    expect(toOptions({ orientation: "across", preset: "small_qr" })).toEqual({ orientation: "across", layout_preset: "small_qr" });
    expect(toOptions({ orientation: "along", preset: "small_qr" })).toEqual({ orientation: "along" });
  });

  it("offers the choice for a QL with 62 mm tape only", () => {
    expect(hasLayoutChoice({ backend: "brother_ql" }, 62)).toBe(true);
    expect(hasLayoutChoice({ backend: "brother_ql" }, 29)).toBe(false);
    expect(hasLayoutChoice({ backend: "ptouch" }, 62)).toBe(false);
    expect(hasLayoutChoice(null, 62)).toBe(false);
  });

  it("reads the tape width from the number, else from the text, else assumes 12", () => {
    expect(tapeMmOfStatus({ tape_loaded: "12mm", tape_width_mm: 62 })).toBe(62);
    expect(tapeMmOfStatus({ tape_loaded: "62mm / 2.4\"" })).toBe(62);
    expect(tapeMmOfStatus(undefined)).toBe(12);
  });
});
