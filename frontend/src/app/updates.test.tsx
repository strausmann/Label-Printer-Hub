// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { act, renderHook, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderApp } from "../test-utils";
import { mockApi } from "../features/test-api";
import {
  applyUpdate,
  dismissUpdateToast,
  noteServerVersion,
  resetUpdatesForTest,
  setVersionCheckForTest,
  startUpdates,
  updateIsReloading,
  updateIsWaiting,
  useUpdateNotice,
} from "./updates";

afterEach(() => {
  resetUpdatesForTest();
  vi.unstubAllGlobals();
});

describe("new version prompt", () => {
  it("appears on needRefresh and its button calls updateSW(true)", async () => {
    mockApi({});
    const updateSW = vi.fn(async () => {});
    let needRefresh!: () => void;
    startUpdates((options) => {
      needRefresh = options.onNeedRefresh;
      return updateSW;
    });
    await renderApp({ path: "/" });
    expect(screen.queryByText("New version available")).toBeNull();

    await act(async () => needRefresh());
    expect(screen.getByRole("status", { name: "" })).toBeDefined();
    expect(screen.getByText("New version available")).toBeVisible();
    // Non-blocking: the page is still there and usable.
    expect(screen.getByRole("main")).toBeVisible();

    const toast = screen.getByRole("region", { name: "New version" });
    await userEvent.click(within(toast).getByRole("button", { name: "Reload" }));
    expect(updateSW).toHaveBeenCalledWith(true);
  });

  it("stays away when the app never reports an update", async () => {
    mockApi({});
    startUpdates(() => async () => {});
    await renderApp({ path: "/" });
    expect(screen.queryByRole("button", { name: "Reload" })).toBeNull();
  });
});

describe("updateIsWaiting", () => {
  it("is false until something waits", () => {
    expect(updateIsWaiting()).toBe(false);
  });

  it("is true when a service worker waits", () => {
    let needRefresh!: () => void;
    startUpdates((options) => {
      needRefresh = options.onNeedRefresh;
      return async () => {};
    });
    needRefresh();
    expect(updateIsWaiting()).toBe(true);
  });

  it("is true when the hub runs another version, and false again once the versions match", () => {
    setVersionCheckForTest({ buildVersion: "1.0.0" });
    noteServerVersion("1.1.0");
    expect(updateIsWaiting()).toBe(true);
    noteServerVersion("1.0.0");
    expect(updateIsWaiting()).toBe(false);
  });
});

describe("updateIsReloading", () => {
  it("is false until applyUpdate has told the page to reload", () => {
    expect(updateIsReloading()).toBe(false);
  });

  it("is true once applyUpdate has told the page to reload", async () => {
    let needRefresh!: () => void;
    startUpdates((options) => {
      needRefresh = options.onNeedRefresh;
      return async () => {};
    });
    needRefresh();
    const reload = vi.fn();
    setVersionCheckForTest({ reload, controllerChanges: async () => true });
    await applyUpdate();
    expect(reload).toHaveBeenCalledTimes(1);
    expect(updateIsReloading()).toBe(true);
  });
});

/** A worker that starts waiting when the returned function is called. */
function workerWaiting(): () => void {
  let needRefresh!: () => void;
  startUpdates((options) => {
    needRefresh = options.onNeedRefresh;
    return async () => {};
  });
  return () => needRefresh();
}

describe("the update notice", () => {
  it("a mismatch names the hub's version", () => {
    setVersionCheckForTest({ buildVersion: "1.0.0" });
    const { result } = renderHook(() => useUpdateNotice());
    expect(result.current).toEqual({ waiting: false, version: null, detectedAt: null, toastOpen: true });
    act(() => noteServerVersion("1.1.0"));
    expect(result.current.waiting).toBe(true);
    expect(result.current.version).toBe("1.1.0");
    expect(result.current.toastOpen).toBe(true);
    expect(Number.isNaN(Date.parse(result.current.detectedAt ?? ""))).toBe(false);
  });

  it("a newer mismatch replaces the version", () => {
    setVersionCheckForTest({ buildVersion: "1.0.0" });
    const { result } = renderHook(() => useUpdateNotice());
    act(() => noteServerVersion("1.1.0"));
    const first = result.current.detectedAt;
    act(() => noteServerVersion("1.2.0"));
    expect(result.current.version).toBe("1.2.0");
    // The notice did not start over: it was waiting all along.
    expect(result.current.detectedAt).toBe(first);
  });

  it("Later closes only the toast", () => {
    setVersionCheckForTest({ buildVersion: "1.0.0" });
    const { result } = renderHook(() => useUpdateNotice());
    act(() => noteServerVersion("1.1.0"));
    act(() => dismissUpdateToast());
    expect(result.current).toMatchObject({ waiting: true, version: "1.1.0", toastOpen: false });
    // For the page's lifetime: a newer version does not bring the toast back.
    act(() => noteServerVersion("1.2.0"));
    expect(result.current).toMatchObject({ waiting: true, version: "1.2.0", toastOpen: false });
  });

  it("a waiting worker alone has no version", () => {
    const needRefresh = workerWaiting();
    const { result } = renderHook(() => useUpdateNotice());
    act(() => needRefresh());
    expect(result.current.waiting).toBe(true);
    expect(result.current.version).toBeNull();
    expect(result.current.detectedAt).not.toBeNull();
  });

  it("the notice goes when the hub reports the bundle's version and no worker waits", () => {
    setVersionCheckForTest({ buildVersion: "1.0.0" });
    const { result } = renderHook(() => useUpdateNotice());
    act(() => noteServerVersion("1.1.0"));
    act(() => noteServerVersion("1.0.0"));
    expect(result.current).toEqual({ waiting: false, version: null, detectedAt: null, toastOpen: true });
  });

  it("a waiting worker keeps the notice after the versions match", () => {
    setVersionCheckForTest({ buildVersion: "1.0.0" });
    const needRefresh = workerWaiting();
    const { result } = renderHook(() => useUpdateNotice());
    act(() => noteServerVersion("1.1.0"));
    act(() => needRefresh());
    const since = result.current.detectedAt;
    act(() => noteServerVersion("1.0.0"));
    expect(result.current.waiting).toBe(true);
    // The worker that waits is the one fetched for 1.1.0: the notice keeps naming it, so its entry keeps its id.
    expect(result.current.version).toBe("1.1.0");
    expect(result.current.detectedAt).toBe(since);
  });

  it("the snapshot is stable between changes", () => {
    setVersionCheckForTest({ buildVersion: "1.0.0" });
    const { result, rerender } = renderHook(() => useUpdateNotice());
    const before = result.current;
    rerender();
    expect(result.current).toBe(before);
    act(() => noteServerVersion("1.1.0"));
    const after = result.current;
    expect(after).not.toBe(before);
    rerender();
    expect(result.current).toBe(after);
  });
});
