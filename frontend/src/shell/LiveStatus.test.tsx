// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { I18nProvider } from "@lingui/react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { i18n, initI18n } from "../i18n";
import { LiveStatus } from "./LiveStatus";

const ui = (connected: boolean, connecting = false, onReconnect: () => void = () => {}) => (
  <I18nProvider i18n={i18n}>
    <LiveStatus connected={connected} connecting={connecting} onReconnect={onReconnect} />
  </I18nProvider>
);

beforeEach(async () => {
  await initI18n("en");
  vi.useFakeTimers();
});
afterEach(() => vi.useRealTimers());

describe("LiveStatus", () => {
  it("stays silent for the first 5 s, then shows the note", () => {
    render(ui(false));
    act(() => void vi.advanceTimersByTime(4_999));
    expect(screen.queryByText("Live updates paused")).toBeNull();
    act(() => void vi.advanceTimersByTime(1));
    expect(screen.getByText("Live updates paused")).toBeVisible();
  });

  it("never shows while connected and clears on reconnect", () => {
    const { rerender } = render(ui(false));
    act(() => void vi.advanceTimersByTime(6_000));
    expect(screen.getByText("Live updates paused")).toBeVisible();
    rerender(ui(true));
    expect(screen.queryByText("Live updates paused")).toBeNull();
  });

  it("offers a reconnect button that calls back", () => {
    const onReconnect = vi.fn();
    render(ui(false, false, onReconnect));
    act(() => void vi.advanceTimersByTime(6_000));
    fireEvent.click(screen.getByRole("button", { name: "Reconnect" }));
    expect(onReconnect).toHaveBeenCalledTimes(1);
  });

  it("disables the button and marks it busy while connecting", () => {
    render(ui(false, true));
    act(() => void vi.advanceTimersByTime(6_000));
    const button = screen.getByRole("button", { name: "Reconnecting…" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-busy", "true");
  });
});
