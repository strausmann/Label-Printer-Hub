import { describe, expect, it } from "vitest";
import { PRINTER_A, status } from "../test-api";
import { describePrinter, parseTape } from "./model";

describe("parseTape", () => {
  it("reads the width alone", () => {
    expect(parseTape("12mm")).toEqual({ widthMm: 12, colourName: null, colour: null });
  });
  it("reads the tape colour before the slash, not the text colour", () => {
    expect(parseTape("12mm laminated blue/white")).toMatchObject({ widthMm: 12, colour: "blue", colourName: "blue" });
  });
  it("keeps an unknown colour name without a swatch", () => {
    expect(parseTape("9mm laminated clear/black")).toMatchObject({ colour: null, colourName: "clear" });
  });
  it("returns null for no tape", () => {
    expect(parseTape(null)).toBeNull();
    expect(parseTape("  ")).toBeNull();
  });
});

describe("describePrinter", () => {
  const ok = status(PRINTER_A.id);
  it("paused wins over offline", () => {
    expect(describePrinter({ ...PRINTER_A, paused: true }, status(PRINTER_A.id, { online: false }), false).kind).toBe("paused");
  });
  it("offline carries the probe error verbatim", () => {
    const view = describePrinter(PRINTER_A, status(PRINTER_A.id, { online: false, last_error: "timed out" }), false);
    expect(view).toMatchObject({ kind: "offline", badge: "bad", detail: "timed out" });
  });
  it("error flags make a problem", () => {
    expect(describePrinter(PRINTER_A, status(PRINTER_A.id, { error_state: "cover open" }), false)).toMatchObject({
      kind: "error",
      detail: "cover open",
    });
  });
  it("printing, ready and unknown", () => {
    expect(describePrinter(PRINTER_A, ok, true).kind).toBe("printing");
    expect(describePrinter(PRINTER_A, ok, false).kind).toBe("ready");
    expect(describePrinter(PRINTER_A, undefined, false)).toMatchObject({ kind: "unknown", badge: "idle" });
  });
});
