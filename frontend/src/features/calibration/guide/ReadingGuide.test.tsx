// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { I18nProvider } from "@lingui/react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeAll, describe, expect, it } from "vitest";
import { i18n, initI18n } from "../../../i18n";
import { GEOMETRY_L4736 } from "../../test-api";
import { ReadingGuide } from "./ReadingGuide";

const TYPE = { geometry: { ...GEOMETRY_L4736, cols: 4, rows: 12 }, label: "Avery L4736REV (4736)" };

beforeAll(() => initI18n("en"));

function show(props: Parameters<typeof ReadingGuide>[0] = { type: TYPE }) {
  return render(
    <I18nProvider i18n={i18n}>
      <ReadingGuide {...props} />
    </I18nProvider>,
  );
}

const open = async () => userEvent.click(screen.getByRole("button", { name: "How to read the calibration page" }));

describe("the reading guide", () => {
  it("the guide is collapsed and opens on press", async () => {
    show();
    const trigger = screen.getByRole("button", { name: "How to read the calibration page" });
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByText(/Print the page on a real sheet/)).not.toBeVisible();
    await userEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(/Print the page on a real sheet/)).toBeVisible();
  });

  it("without a type it shows the crossing figure and the steps, not the sheet figure", async () => {
    show({});
    await open();
    expect(screen.getByRole("img", { name: "How to read one crossing" })).toBeVisible();
    expect(screen.queryByRole("img", { name: /The crossings to read on/ })).toBeNull();
    expect(screen.getByRole("list", { name: "Steps" })).toBeVisible();
  });

  it("the sheet figure marks the five crossings of the chosen type and the legend names them", async () => {
    show();
    await open();
    const sheet = screen.getByRole("img", { name: /The crossings to read on/ });
    const marks = [...sheet.querySelectorAll("[data-crossing]")].map((m) => m.getAttribute("data-crossing"));
    expect(marks).toEqual(["S1-Z1", "S3-Z1", "S1-Z11", "S3-Z11", "S2-Z6"]);
    const legend = screen.getByRole("list", { name: "The crossings to read" });
    const names = within(legend).getAllByRole("listitem").map((li) => li.textContent);
    expect(names).toEqual(["S1 · Z1", "S3 · Z1", "S1 · Z11", "S3 · Z11", "S2 · Z6 (centre)"]);
  });

  it("both figures have their accessible names", async () => {
    show();
    await open();
    expect(screen.getByRole("img", { name: "How to read one crossing" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "The crossings to read on Avery L4736REV (4736)" })).toBeInTheDocument();
  });

  it("the steps state the signs", async () => {
    show();
    await open();
    expect(screen.getByText(/\+ across = the ink lies right of the middle of the gap/)).toBeInTheDocument();
    expect(screen.getByText(/\+ down = the ink lies below the cut/)).toBeInTheDocument();
  });

  it("the link goes to labelyard.app in the UI language and opens a new tab", async () => {
    show();
    await open();
    const en = screen.getByRole("link", { name: /More on labelyard\.app/ });
    expect(en).toHaveAttribute("href", "https://labelyard.app/using/calibration/");
    expect(en).toHaveAttribute("target", "_blank");
    expect(en).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("the link goes to the German page when the UI is German", async () => {
    await initI18n("de");
    try {
      show();
      await userEvent.click(screen.getByRole("button", { name: "So liest du die Kalibrierseite ab" }));
      const de = screen.getByRole("link", { name: /Mehr auf labelyard\.app/ });
      expect(de).toHaveAttribute("href", "https://labelyard.app/de/using/calibration/");
      expect(de).toHaveAttribute("target", "_blank");
      expect(de).toHaveAttribute("rel", "noopener noreferrer");
      expect(screen.getByRole("img", { name: "So liest du eine Kreuzung ab" })).toBeInTheDocument();
      expect(screen.getByRole("img", { name: "Die abzulesenden Kreuzungen auf Avery L4736REV (4736)" })).toBeInTheDocument();
    } finally {
      await initI18n("en");
    }
  });

  it("the figures use no colour", async () => {
    const { container } = show();
    await open();
    const used = new Set<string>();
    for (const el of container.querySelectorAll("svg, svg *")) {
      for (const attr of ["fill", "stroke", "stop-color", "color"]) {
        const v = el.getAttribute(attr);
        if (v) used.add(v);
      }
      expect((el as SVGElement).style?.cssText ?? "").not.toMatch(/(fill|stroke|color)\s*:/);
    }
    expect([...used].filter((v) => v !== "currentColor" && v !== "none")).toEqual([]);
    expect(container.querySelectorAll("svg[role=\"img\"]").length).toBe(2);
  });

  it("the figures carry no words", async () => {
    const { container } = show();
    await open();
    const texts = [...container.querySelectorAll("svg text")].map((t) => t.textContent ?? "");
    expect(texts.length).toBeGreaterThan(10);
    for (const text of texts) expect(text).toMatch(/^[SZ]?[0-9+−±.,]*$/);
  });

  it("two figures on one page share no id", async () => {
    const { container } = show();
    await open();
    const ids = [...container.querySelectorAll("[id]")].map((e) => e.id).filter((id) => id.length > 0);
    // The guide's own panel ids are not part of the figures; the figures' ids must be unique among all.
    expect(new Set(ids).size).toBe(ids.length);
    const figureIds = [...container.querySelectorAll("svg [id]")].map((e) => e.id);
    expect(figureIds.length).toBeGreaterThan(0);
    for (const id of figureIds) expect(id).toMatch(/^[A-Za-z0-9_-]+$/);
  });
});
