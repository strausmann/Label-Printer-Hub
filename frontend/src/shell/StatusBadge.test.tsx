// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { I18nProvider } from "@lingui/react";
import { i18n, initI18n } from "../i18n";
import { StatusBadge, type BadgeState } from "./StatusBadge";

async function renderBadge(state: BadgeState, label: string) {
  await initI18n("en");
  return render(
    <I18nProvider i18n={i18n}>
      <StatusBadge state={state} label={label} />
    </I18nProvider>,
  );
}

describe("StatusBadge", () => {
  it("warn renders a diamond and the label", async () => {
    const { container } = await renderBadge("warn", "Tape low");
    expect(container.querySelector('[data-shape="diamond"]')).not.toBeNull();
    expect(container.querySelector('[data-shape="dot"]')).toBeNull();
    expect(screen.getByText("Tape low")).toBeVisible();
  });

  it.each(["ok", "bad", "idle"] as const)("%s renders a dot, not a diamond", async (state) => {
    const { container } = await renderBadge(state, "Label");
    expect(container.querySelector('[data-shape="dot"]')).not.toBeNull();
    expect(container.querySelector('[data-shape="diamond"]')).toBeNull();
  });

  it("never renders without text", async () => {
    for (const state of ["ok", "warn", "bad", "idle"] as const) {
      const { container, unmount } = await renderBadge(state, state === "ok" ? "Ready" : "");
      // The visible text, not the shape, carries the state: it is never empty.
      expect(container.textContent?.trim().length ?? 0).toBeGreaterThan(0);
      if (state === "ok") expect(screen.getByText("Ready")).toBeVisible();
      unmount();
    }
  });

  it("falls back to the state word when the label is blank", async () => {
    await renderBadge("bad", "   ");
    expect(screen.getByText("Problem")).toBeVisible();
  });
});
