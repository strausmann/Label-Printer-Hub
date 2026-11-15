// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { DESKTOP_QUERY, useIsDesktop } from "./useIsDesktop";

/** A matchMedia whose answer for the desktop query a test can change at any time. */
function fakeMedia(width: number) {
  let current = width;
  const listeners = new Set<() => void>();
  window.matchMedia = ((query: string) => ({
    matches: query === DESKTOP_QUERY ? current >= 1024 : false,
    media: query,
    addEventListener: (_: string, fn: () => void) => listeners.add(fn),
    removeEventListener: (_: string, fn: () => void) => listeners.delete(fn),
  })) as unknown as typeof window.matchMedia;
  return {
    resize(next: number) {
      current = next;
      act(() => listeners.forEach((fn) => fn()));
    },
    listeners,
  };
}

afterEach(() => {
  delete (window as { matchMedia?: unknown }).matchMedia;
});

describe("useIsDesktop", () => {
  it("is true at 1024 px and above, false below", () => {
    fakeMedia(1024);
    expect(renderHook(() => useIsDesktop()).result.current).toBe(true);
    fakeMedia(1023);
    expect(renderHook(() => useIsDesktop()).result.current).toBe(false);
  });

  it("follows a change of the media query, and stops listening when unmounted", () => {
    const media = fakeMedia(1280);
    const { result, unmount } = renderHook(() => useIsDesktop());
    expect(result.current).toBe(true);
    media.resize(390);
    expect(result.current).toBe(false);
    media.resize(1100);
    expect(result.current).toBe(true);
    unmount();
    expect(media.listeners.size).toBe(0);
  });

  it("is true without matchMedia, so a test without it keeps the inline field", () => {
    expect((window as { matchMedia?: unknown }).matchMedia).toBeUndefined();
    expect(renderHook(() => useIsDesktop()).result.current).toBe(true);
  });
});
