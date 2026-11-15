// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { I18nProvider } from "@lingui/react";
import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it } from "vitest";
import { i18n, initI18n } from "../../../i18n";
import { StillOff } from "./StillOff";

beforeAll(() => initI18n("en"));
afterEach(() => initI18n("en"));

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
    for (const row of rows) expect(row.textContent).not.toMatch(/\b(the|sheet type|Calibrate|correction)\b/);
    const link = screen.getByRole("link", { name: /Mehr in der Anleitung/ });
    expect(link).toHaveAttribute("href", "https://labelyard.app/de/using/calibration/#drucker-oder-bogentyp");
  });
});
