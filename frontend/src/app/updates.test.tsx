// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { act, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderApp } from "../test-utils";
import { mockApi } from "../features/test-api";
import { applyUpdate, noteServerVersion, resetUpdatesForTest, setVersionCheckForTest, startUpdates, updateIsReloading, updateIsWaiting } from "./updates";

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

    await userEvent.click(screen.getByRole("button", { name: "Reload" }));
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
