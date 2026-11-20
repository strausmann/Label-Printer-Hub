// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { render, screen } from "@testing-library/react";
import { I18nProvider } from "@lingui/react";
import { beforeEach, describe, expect, it } from "vitest";
import { i18n, initI18n } from "../../i18n";
import { pageStatus } from "../test-api";
import { MarkerList, noAnswerYet, ReasonLine, supplyEmpty, supplyLowOnly } from "./PageStatus";

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

describe("supplyLowOnly and supplyEmpty", () => {
  const marker = { name: "x", color: null, level_percent: 50, low: false, empty: false, some_remaining: false, type: null };
  it("tell a low supply from an empty one", () => {
    const low = pageStatus(ID, { markers: [{ ...marker, low: true }] });
    const empty = pageStatus(ID, { markers: [{ ...marker }, { ...marker, empty: true }] });
    expect(supplyLowOnly(low)).toBe(true);
    expect(supplyEmpty(low)).toBe(false);
    expect(supplyEmpty(empty)).toBe(true);
    expect(supplyLowOnly(empty)).toBe(false);
  });
  it("an empty supply that is also flagged low counts as empty only", () => {
    const both = pageStatus(ID, { markers: [{ ...marker, low: true, empty: true }] });
    expect(supplyEmpty(both)).toBe(true);
    expect(supplyLowOnly(both)).toBe(false);
  });
  it("a printer with one empty and one low supply counts in both", () => {
    const mixed = pageStatus(ID, { markers: [{ ...marker, empty: true }, { ...marker, low: true }] });
    expect(supplyEmpty(mixed)).toBe(true);
    expect(supplyLowOnly(mixed)).toBe(true);
  });
  it("a status nobody refreshes counts as nothing (its row says supplies not known)", () => {
    const markers = [{ ...marker, empty: true }, { ...marker, low: true }];
    for (const over of [{ stale: true }, { polled: false }]) {
      const unknown = pageStatus(ID, { markers, ...over });
      expect(supplyEmpty(unknown)).toBe(false);
      expect(supplyLowOnly(unknown)).toBe(false);
    }
  });
  it("nothing else counts", () => {
    for (const status of [pageStatus(ID, { markers: [{ ...marker }] }), pageStatus(ID, { markers: null }), undefined]) {
      expect(supplyLowOnly(status)).toBe(false);
      expect(supplyEmpty(status)).toBe(false);
    }
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
  it("names the keywords in words, joined", () => {
    render(wrap(<ReasonLine reasons={["toner-empty", "media-low"]} />));
    expect(screen.getByText("toner empty · media low")).toBeVisible();
  });
  it("shows an unknown keyword verbatim, not in the code font", () => {
    const { container } = render(wrap(<ReasonLine reasons={["developer-low"]} />));
    expect(screen.getByText("developer-low")).toBeVisible();
    expect(container.querySelector("code")).toBeNull();
  });
  it("is silent without reasons", () => {
    const { container } = render(wrap(<ReasonLine reasons={[]} />));
    expect(container).toBeEmptyDOMElement();
  });
});
