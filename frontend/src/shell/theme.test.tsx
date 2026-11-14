// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { I18nProvider } from "@lingui/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { i18n, initI18n } from "../i18n";
import { THEME_KEY, applyTheme, readTheme, storeTheme } from "./theme";
import { ThemeSwitch } from "./ThemeSwitch";

afterEach(() => {
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
  vi.restoreAllMocks();
});

describe("theme storage", () => {
  it("defaults to system", () => {
    expect(readTheme()).toBe("system");
  });

  it("uses the lph.theme key", () => {
    storeTheme("dark");
    expect(localStorage.getItem("lph.theme")).toBe("dark");
    expect(THEME_KEY).toBe("lph.theme");
    expect(readTheme()).toBe("dark");
  });

  it("ignores garbage and a throwing storage", () => {
    localStorage.setItem(THEME_KEY, "purple");
    expect(readTheme()).toBe("system");
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(readTheme()).toBe("system");
    expect(() => storeTheme("light")).not.toThrow();
  });

  it("sets data-theme for light and dark and removes it for system", () => {
    applyTheme("dark");
    expect(document.documentElement).toHaveAttribute("data-theme", "dark");
    applyTheme("light");
    expect(document.documentElement).toHaveAttribute("data-theme", "light");
    applyTheme("system");
    expect(document.documentElement).not.toHaveAttribute("data-theme");
  });
});

describe("ThemeSwitch", () => {
  async function renderSwitch() {
    await initI18n("en");
    render(
      <I18nProvider i18n={i18n}>
        <ThemeSwitch />
      </I18nProvider>,
    );
  }

  it("applies and remembers the choice", async () => {
    await renderSwitch();
    expect(screen.getByRole("radio", { name: "System theme" })).toBeChecked();
    await userEvent.click(screen.getByRole("radio", { name: "Dark theme" }));
    expect(document.documentElement).toHaveAttribute("data-theme", "dark");
    expect(localStorage.getItem(THEME_KEY)).toBe("dark");
    await userEvent.click(screen.getByRole("radio", { name: "System theme" }));
    expect(document.documentElement).not.toHaveAttribute("data-theme");
  });

  it("starts from the stored choice", async () => {
    storeTheme("light");
    await renderSwitch();
    expect(screen.getByRole("radio", { name: "Light theme" })).toBeChecked();
  });
});
