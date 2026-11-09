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

describe("describePrinter for a status nobody refreshes (#227)", () => {
  it("describePrinter stale row is not ready", () => {
    const view = describePrinter(PRINTER_A, status(PRINTER_A.id, { online: true, stale: true }), false);
    expect(view).toMatchObject({ kind: "stale", badge: "idle" });
  });
  it("describePrinter unpolled", () => {
    expect(describePrinter(PRINTER_A, status(PRINTER_A.id, { online: null, polled: false }), false)).toMatchObject({
      kind: "not_polled",
      badge: "idle",
    });
  });
  it("unpolled wins over stale, paused wins over both", () => {
    expect(describePrinter(PRINTER_A, status(PRINTER_A.id, { polled: false, stale: true }), false).kind).toBe("not_polled");
    expect(describePrinter({ ...PRINTER_A, paused: true }, status(PRINTER_A.id, { stale: true }), false).kind).toBe("paused");
  });
  it("a fresh, polled status is untouched", () => {
    expect(describePrinter(PRINTER_A, status(PRINTER_A.id, { stale: false, polled: true }), false).kind).toBe("ready");
  });
});

describe("describePrinter for a page printer", () => {
  const PAGE = { ...PRINTER_A, backend: "ipp" };
  const page = (over: Record<string, unknown> = {}) => status(PAGE.id, { kind: "page", tape_loaded: null, printer_state: "idle", state_reasons: [], ...over });

  it("an idle, answering page printer is ready", () => {
    expect(describePrinter(PAGE, page(), false)).toMatchObject({ kind: "ready", badge: "ok", reasons: [] });
  });
  it("a stopped printer says Stopped and keeps the blocking keywords", () => {
    const view = describePrinter(
      PAGE,
      page({ printer_state: "stopped", state_reasons: [{ keyword: "toner-empty", severity: "error", blocking: true }] }),
      false,
    );
    expect(view).toMatchObject({ kind: "stopped", badge: "bad", reasons: ["toner-empty"] });
  });
  it("a stopped printer is Stopped, not Problem, even though error_state repeats its keywords", () => {
    const view = describePrinter(
      PAGE,
      page({ printer_state: "stopped", error_state: "toner-empty", state_reasons: [{ keyword: "toner-empty", severity: "error", blocking: true }] }),
      false,
    );
    expect(view).toMatchObject({ kind: "stopped", detail: null });
  });
  it("idle with a blocking reason is a problem named by its keyword, not by the raw error text", () => {
    const view = describePrinter(
      PAGE,
      page({ error_state: "media-empty", state_reasons: [{ keyword: "media-empty", severity: "error", blocking: true }] }),
      false,
    );
    expect(view).toMatchObject({ kind: "error", badge: "bad", detail: null, reasons: ["media-empty"] });
  });
  it("without a blocking reason the error text itself is the keyword", () => {
    expect(describePrinter(PAGE, page({ error_state: "developer-low" }), false)).toMatchObject({
      kind: "error",
      detail: null,
      reasons: ["developer-low"],
    });
  });
  it("a tape printer with error flags and a stopped state keeps its error text", () => {
    const view = describePrinter(PRINTER_A, status(PRINTER_A.id, { error_state: "cover open", printer_state: "stopped" }), false);
    expect(view).toMatchObject({ kind: "error", detail: "cover open", reasons: [] });
  });
  it("a stopped printer with only a warning is a warning, with that keyword", () => {
    const view = describePrinter(
      PAGE,
      page({ printer_state: "stopped", state_reasons: [{ keyword: "toner-low", severity: "warning", blocking: false }] }),
      false,
    );
    expect(view).toMatchObject({ kind: "stopped", badge: "warn", reasons: ["toner-low"] });
  });
  it("report-level reasons are not shown", () => {
    const view = describePrinter(
      PAGE,
      page({ printer_state: "stopped", state_reasons: [{ keyword: "cups-info", severity: "report", blocking: false }] }),
      false,
    );
    expect(view.reasons).toEqual([]);
  });
  it("printing at the printer counts as printing even without a hub job", () => {
    expect(describePrinter(PAGE, page({ printer_state: "printing" }), false).kind).toBe("printing");
  });
  it("paused and offline still win", () => {
    expect(describePrinter({ ...PAGE, paused: true }, page({ printer_state: "stopped" }), false).kind).toBe("paused");
    expect(describePrinter(PAGE, page({ online: false, printer_state: "stopped" }), false).kind).toBe("offline");
  });
  it("a printer that never answered stays unknown", () => {
    expect(describePrinter(PAGE, page({ online: null, printer_state: null, captured_at: null }), false).kind).toBe("unknown");
  });
  it("a tape printer never becomes stopped", () => {
    const view = describePrinter(PRINTER_A, status(PRINTER_A.id, { printer_state: "stopped" }), false);
    expect(view.kind).toBe("ready");
    expect(view.reasons).toEqual([]);
  });
});
