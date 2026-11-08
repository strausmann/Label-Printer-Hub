import { render, screen } from "@testing-library/react";
import { I18nProvider } from "@lingui/react";
import { beforeEach, describe, expect, it } from "vitest";
import { i18n, initI18n } from "../../i18n";
import { pageStatus } from "../test-api";
import { MarkerList, noAnswerYet, ReasonLine, runningOut } from "./PageStatus";

const wrap = (node: React.ReactNode) => <I18nProvider i18n={i18n}>{node}</I18nProvider>;
const ID = "33333333-3333-4333-8333-333333333333";

describe("noAnswerYet (#206)", () => {
  it("is true when nothing is known", () => {
    expect(noAnswerYet(undefined)).toBe(true);
    expect(noAnswerYet(pageStatus(ID, { online: null, markers: [], trays: [], captured_at: "2026-11-04T10:00:00Z" }))).toBe(true);
    expect(noAnswerYet(pageStatus(ID, { online: null, markers: null, trays: null }))).toBe(true);
  });
  it("is false once the printer answered or any marker or tray is known", () => {
    expect(noAnswerYet(pageStatus(ID))).toBe(false);
    expect(noAnswerYet(pageStatus(ID, { online: false }))).toBe(false);
    expect(noAnswerYet(pageStatus(ID, { online: null, trays: null }))).toBe(false);
    expect(noAnswerYet(pageStatus(ID, { online: null, markers: [], trays: pageStatus(ID).trays }))).toBe(false);
  });
});

describe("runningOut", () => {
  const marker = { name: "x", color: null, level_percent: 50, low: false, empty: false, some_remaining: false, type: null };
  it("counts low and empty markers, nothing else", () => {
    expect(runningOut(pageStatus(ID, { markers: [{ ...marker, low: true }] }))).toBe(true);
    expect(runningOut(pageStatus(ID, { markers: [{ ...marker }, { ...marker, empty: true }] }))).toBe(true);
    expect(runningOut(pageStatus(ID, { markers: [{ ...marker }] }))).toBe(false);
    expect(runningOut(pageStatus(ID, { markers: null }))).toBe(false);
    expect(runningOut(undefined)).toBe(false);
  });
});

describe("MarkerList", () => {
  beforeEach(async () => {
    await initI18n("en");
  });
  it("says so when the printer reports no supplies", () => {
    render(wrap(<MarkerList markers={[]} />));
    expect(screen.getByText("No supplies reported")).toBeVisible();
  });
  it("lists every marker, even many", () => {
    const markers = Array.from({ length: 9 }, (_, i) => ({
      name: `Supply ${i}`,
      color: null,
      level_percent: i * 10,
      low: false,
      empty: false,
      some_remaining: false,
      type: null,
    }));
    render(wrap(<MarkerList markers={markers} />));
    expect(screen.getAllByRole("listitem")).toHaveLength(9);
  });
});

describe("ReasonLine", () => {
  beforeEach(async () => {
    await initI18n("en");
  });
  const reason = (keyword: string, severity: "report" | "warning" | "error", blocking: boolean) => ({ keyword, severity, blocking });

  it("names the blocking reasons of a stopped printer", () => {
    render(
      wrap(<ReasonLine status={pageStatus(ID, { printer_state: "stopped", state_reasons: [reason("toner-empty", "error", true), reason("media-low", "warning", false)] })} />),
    );
    expect(screen.getByText("toner empty")).toBeVisible();
    expect(screen.queryByText(/media low/)).toBeNull();
  });
  it("falls back to the warnings when nothing blocks", () => {
    render(wrap(<ReasonLine status={pageStatus(ID, { printer_state: "stopped", state_reasons: [reason("toner-low", "warning", false)] })} />));
    expect(screen.getByText("toner low")).toBeVisible();
  });
  it("shows an unknown keyword verbatim", () => {
    render(wrap(<ReasonLine status={pageStatus(ID, { printer_state: "stopped", state_reasons: [reason("developer-low", "error", true)] })} />));
    expect(screen.getByText("developer-low")).toBeVisible();
  });
  it("is silent for a printer that is not stopped", () => {
    const { container } = render(wrap(<ReasonLine status={pageStatus(ID, { state_reasons: [reason("toner-low", "warning", false)] })} />));
    expect(container).toBeEmptyDOMElement();
  });
});
