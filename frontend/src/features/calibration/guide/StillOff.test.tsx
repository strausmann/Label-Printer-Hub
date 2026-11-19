// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { I18nProvider } from "@lingui/react";
import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it } from "vitest";
import { i18n, initI18n } from "../../../i18n";
import { ANCHOR, StillOff } from "./StillOff";

beforeAll(() => initI18n("en"));
afterEach(() => initI18n("en"));

const ROWS_EN = [
  "The whole page is off by the same shift",
  "The deviation grows with the distance, or a line leans or the rows tilt, on every sheet type",
  "Only one sheet type is off; other sheets sit with the same correction",
  "The shift differs from sheet to sheet",
];
const ROWS_DE = [
  "Die ganze Seite ist um denselben Versatz verschoben",
  "Die Abweichung wächst mit dem Abstand, oder eine Linie steht schief oder die Zeilen kippen, auf jedem Bogentyp",
  "Nur ein Bogentyp liegt daneben; andere Bögen sitzen mit derselben Korrektur",
  "Der Versatz ist von Blatt zu Blatt verschieden",
];

const show = () =>
  render(
    <I18nProvider i18n={i18n}>
      <StillOff />
    </I18nProvider>,
  );

describe("the still-off card", () => {
  it("renders the four main rows with what to do", () => {
    show();
    expect(screen.getByRole("heading", { name: "Still off after the check print?" })).toBeVisible();
    const rows = within(screen.getByRole("list", { name: "What the deviation tells you" })).getAllByRole("listitem");
    expect(rows).toHaveLength(4);
    expect(rows[0]).toHaveTextContent("The whole page is off by the same shift");
    expect(rows[1]).toHaveTextContent("grows with the distance");
    expect(rows[2]).toHaveTextContent("Correct that sheet type (add a new version), not the printer.");
    expect(rows[3]).toHaveTextContent("differs from sheet to sheet");
  });

  it("links to the table on labelyard.app in a new tab", () => {
    show();
    const link = screen.getByRole("link", { name: /More in the guide/ });
    expect(link).toHaveAttribute("href", "https://labelyard.app/using/calibration/#printer-or-sheet-type");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("is complete in German: no English left, the link goes to the German page", async () => {
    await initI18n("de");
    show();
    expect(screen.getByRole("heading", { name: "Noch daneben nach dem Kontrolldruck?" })).toBeVisible();
    const rows = within(screen.getByRole("list", { name: "Was die Abweichung dir sagt" })).getAllByRole("listitem");
    expect(rows).toHaveLength(4);
    // Each row is the exact German text and not its English source: an untranslated string fails here.
    rows.forEach((row, i) => {
      expect(row).toHaveTextContent(ROWS_DE[i]!);
      expect(row.textContent).not.toContain(ROWS_EN[i]!);
    });
    expect(within(rows[0]!).getByText("Kalibrieren: Die Korrektur gleicht es aus.")).toBeVisible();
    expect(within(rows[2]!).getByText("Korrigiere diesen Bogentyp (neue Fassung anlegen), nicht den Drucker.")).toBeVisible();
    expect(within(rows[3]!).getByText(/Es ist der Papiereinzug/)).toBeVisible();
    const link = screen.getByRole("link", { name: /Mehr in der Anleitung/ });
    expect(link).toHaveAttribute("href", "https://labelyard.app/de/using/calibration/#drucker-oder-bogentyp");
  });

  // The link's anchors are the slugs of the headings of the docs page (github-slugger rules: lower case,
  // punctuation dropped, spaces to hyphens); renaming a heading must turn this red.
  it.each([
    ["en", "using/calibration.mdx"],
    ["de", "de/using/calibration.mdx"],
  ] as const)("the %s anchor is the slug of a heading of the docs page", (lang, file) => {
    const text = readFileSync(resolve(__dirname, "../../../../../website/src/content/docs", file), "utf8");
    const slugs = [...text.matchAll(/^#{2,3} (.+)$/gm)].map((m) => m[1]!.toLowerCase().replace(/[^\p{L}\p{N} -]/gu, "").trim().replace(/ /g, "-"));
    expect(slugs).toContain(ANCHOR[lang]);
  });
});
