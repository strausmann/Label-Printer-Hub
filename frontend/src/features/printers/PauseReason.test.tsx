// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { render, screen } from "@testing-library/react";
import { I18nProvider } from "@lingui/react";
import { beforeEach, describe, expect, it } from "vitest";
import { i18n, initI18n } from "../../i18n";
import { PauseReason } from "./PauseReason";

const pause = (reason_code: string) => ({ source: "printer_error" as const, reason_code, since: "2026-11-04T10:00:00Z" });
const ui = (code: string) => (
  <I18nProvider i18n={i18n}>
    <PauseReason pause={pause(code)} />
  </I18nProvider>
);

describe("PauseReason", () => {
  beforeEach(async () => {
    await initI18n("en");
  });

  it("a tape code keeps its sentence", () => {
    render(ui("tape_empty"));
    expect(screen.getByText("Tape is empty")).toBeVisible();
  });

  it("the hub's status-unavailable hold reads as a sentence, not the code font", () => {
    const { container } = render(ui("status-unavailable"));
    expect(screen.getByText("Waiting for the printer's status check")).toBeVisible();
    expect(container.querySelector("code")).toBeNull();
  });

  it("a page printer keyword falls back to its words, not the code font", () => {
    const { container } = render(ui("toner-empty"));
    expect(screen.getByText("toner empty")).toBeVisible();
    expect(container.querySelector("code")).toBeNull();
  });

  it("the hub's own not_accepting code reads as words", () => {
    render(ui("not_accepting"));
    expect(screen.getByText("not accepting jobs")).toBeVisible();
  });

  it("an unknown code stays verbatim in the code font", () => {
    const { container } = render(ui("flux_capacitor"));
    expect(container.querySelector("code")).toHaveTextContent("flux_capacitor");
  });

  it("renders nothing without pause details", () => {
    const { container } = render(
      <I18nProvider i18n={i18n}>
        <PauseReason pause={null} />
      </I18nProvider>,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
