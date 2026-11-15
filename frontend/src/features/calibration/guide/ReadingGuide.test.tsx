// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { I18nProvider } from "@lingui/react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeAll, describe, expect, it } from "vitest";
import { i18n, initI18n } from "../../../i18n";
import { GEOMETRY_L4736 } from "../../test-api";
import { CrossingFigure } from "./CrossingFigure";
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
    for (const id of figureIds) expect(id).toMatch(/^[A-Za-z0-9_-]+$/);
  });
});

// The scale labels are the value to enter, not the position on the scale. The fit takes printed = nominal +
// reading (backend/app/calibration/fit.py), so a reading is positive when the ink lies right of the gap
// middle / below the cut, i.e. when the gap middle lies LEFT of / the cut ABOVE the printed line, which is
// the centre of the scale at (120, 100), 40 units per mm.
describe("the crossing figure's scale labels are the value to enter", () => {
  const num = (text: string) => Number(text.replace("−", "-"));
  const labels = (container: Element) => [...container.querySelectorAll("text")].map((t) => ({ text: t.textContent ?? "", x: Number(t.getAttribute("x")), y: Number(t.getAttribute("y")) }));

  it("the figure's label at the gap middle is the value to enter", () => {
    const { container } = render(<CrossingFigure />);
    const gapMiddleX = Number(container.querySelector('line[stroke-dasharray="1 3 7 3"]')!.getAttribute("x1"));
    const cutY = Number(container.querySelectorAll("rect")[0]!.getAttribute("y")) + Number(container.querySelectorAll("rect")[0]!.getAttribute("height"));
    // The example of the legend: across +0.6, down +0.4.
    expect((120 - gapMiddleX) / 40).toBeCloseTo(0.6);
    expect((100 - cutY) / 40).toBeCloseTo(0.4);
    // The across scale labels sit under the Z line (y 128); the label nearest the gap middle is +1, on the left.
    const across = labels(container).filter((l) => l.y === 128);
    const nearest = across.reduce((a, b) => (Math.abs(a.x - gapMiddleX) < Math.abs(b.x - gapMiddleX) ? a : b));
    expect(nearest.text).toBe("+1");
    expect(nearest.x).toBeLessThan(120);
  });

  it("a label left of 0 is positive and one right of 0 negative; above 0 positive, below negative", () => {
    const { container } = render(<CrossingFigure />);
    const all = labels(container);
    const across = all.filter((l) => l.y === 128);
    const down = all.filter((l) => l.x === 142 && /^[+−][12]$/.test(l.text));
    expect(across).toHaveLength(4);
    expect(down).toHaveLength(4);
    // value to enter = - position on the scale (the position is the offset of the gap middle from the printed line).
    for (const l of across) expect(num(l.text)).toBe(-(l.x - 120) / 40);
    for (const l of down) expect(num(l.text)).toBe(-(l.y - 3.5 - 100) / 40);
  });

  it("no element of the figure states a sign except the scale labels", () => {
    const { container } = render(<CrossingFigure />);
    const signed = labels(container).filter((l) => /[+−]/.test(l.text));
    expect(signed).toHaveLength(8);
    for (const l of signed) expect(l.y === 128 || l.x === 142).toBe(true);
    expect(container.querySelector("marker")).toBeNull();
  });

  it("the legend says the numbers are the value to enter", async () => {
    show();
    await open();
    expect(screen.getByText(/The numbers on the scale are the value to enter/)).toBeVisible();
  });
});

describe("the guide follows what the page offers", () => {
  it("on a 4 × 12 type: five crossings and the fit step", async () => {
    show();
    await open();
    expect(screen.getByText(/Read at least the four outer crossings and the one in the centre/)).toBeInTheDocument();
    expect(screen.getByText(/press Fit/)).toBeInTheDocument();
    expect(screen.queryByText(/cannot be fitted/)).toBeNull();
  });

  it.each([
    ["2 columns", 2, 12],
    ["2 rows", 4, 2],
  ])("on a type with %s: no Fit step, the values are entered directly", async (_name, cols, rows) => {
    show({ type: { geometry: { ...GEOMETRY_L4736, cols, rows }, label: "Avery L4736REV (4736)" } });
    await open();
    expect(screen.queryByText(/four outer crossings and the one in the centre/)).toBeNull();
    expect(screen.queryByText(/press Fit/)).toBeNull();
    expect(screen.getByText(/Read the crossings marked in the drawing/)).toBeInTheDocument();
    expect(screen.getByText(/all crossings lie on one line, so the readings cannot be fitted/)).toBeInTheDocument();
  });
});

