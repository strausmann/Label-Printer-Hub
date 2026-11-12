import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { apiFetch } from "../api/client";
import { mockApi } from "../features/test-api";
import { renderApp } from "../test-utils";
import {
  BUILD_VERSION,
  RELOAD_GUARD_KEY,
  UPDATE_CHECK_INTERVAL_MS,
  noteServerVersion,
  resetUpdatesForTest,
  setVersionCheckForTest,
  startUpdates,
} from "./updates";

// A page built for 1.5.0 talking to a hub that reports 1.6.0 (#288).
const BUILT_FOR = "1.5.0";
const SERVER = "1.6.0";

let reload: Mock<() => void>;

beforeEach(() => {
  window.sessionStorage.clear();
  reload = vi.fn<() => void>();
  setVersionCheckForTest({ buildVersion: BUILT_FOR, reload });
});

afterEach(() => {
  resetUpdatesForTest();
  window.sessionStorage.clear();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("version mismatch", () => {
  it("reloads exactly once, however many responses report the new version, and shows no banner meanwhile", async () => {
    mockApi({});
    await renderApp({ path: "/" });
    await act(async () => {
      noteServerVersion(SERVER);
      noteServerVersion(SERVER);
      noteServerVersion(SERVER);
    });
    expect(reload).toHaveBeenCalledTimes(1);
    // Parallel responses of one page load must not look like "the reload did not help".
    expect(screen.queryByText("New version available")).toBeNull();
  });

  it("does nothing while the versions are equal or the server names none", () => {
    noteServerVersion(BUILT_FOR);
    noteServerVersion(null);
    noteServerVersion(undefined);
    noteServerVersion("");
    expect(reload).not.toHaveBeenCalled();
  });

  it("activates a waiting service worker instead of a plain reload", () => {
    const updateSW = vi.fn(async () => {});
    let needRefresh!: () => void;
    startUpdates((options) => {
      needRefresh = options.onNeedRefresh;
      return updateSW;
    });
    needRefresh();
    noteServerVersion(SERVER);
    expect(updateSW).toHaveBeenCalledWith(true);
    expect(reload).not.toHaveBeenCalled();
  });

  it("shows the banner and does not reload again when the reload did not help", async () => {
    mockApi({});
    noteServerVersion(SERVER);
    expect(reload).toHaveBeenCalledTimes(1);
    expect(window.sessionStorage.getItem(RELOAD_GUARD_KEY)).toBe(SERVER);

    // The reloaded page is the same old bundle (the old service worker served it again).
    resetUpdatesForTest();
    setVersionCheckForTest({ buildVersion: BUILT_FOR, reload });
    await renderApp({ path: "/" });
    expect(screen.queryByText("New version available")).toBeNull();
    await act(async () => noteServerVersion(SERVER));
    await act(async () => noteServerVersion(SERVER));

    expect(reload).toHaveBeenCalledTimes(1);
    expect(screen.getByText("New version available")).toBeVisible();
    // Its button reloads by hand: nothing waits in the service worker.
    await act(async () => screen.getByRole("button", { name: "Reload" }).click());
    expect(reload).toHaveBeenCalledTimes(2);
  });

  it("forgets the guard once the page runs the version the server reports", () => {
    window.sessionStorage.setItem(RELOAD_GUARD_KEY, SERVER);
    setVersionCheckForTest({ buildVersion: SERVER });
    noteServerVersion(SERVER);
    expect(window.sessionStorage.getItem(RELOAD_GUARD_KEY)).toBeNull();
    // A later release is a new target and reloads again.
    noteServerVersion("1.7.0");
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("reads the version from the header of an API response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("{}", { status: 200, headers: { "Content-Type": "application/json", "X-Hub-Version": SERVER } })),
    );
    await apiFetch("/api/v1/info");
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("reads the version from an error response too", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 404, headers: { "X-Hub-Version": SERVER } })));
    await expect(apiFetch("/api/v1/nope")).rejects.toThrow();
    expect(reload).toHaveBeenCalledTimes(1);
  });
});

describe("open dialog with typed input", () => {
  function dialog(value: string) {
    return render(
      <div role="dialog" aria-label="Add sheet">
        <input aria-label="Code" defaultValue={value} />
      </div>,
    );
  }

  it("shows the banner first and reloads when the dialog closes", async () => {
    mockApi({});
    const view = dialog("L4736");
    await act(async () => noteServerVersion(SERVER));
    expect(reload).not.toHaveBeenCalled();

    view.unmount();
    // The observer fires after the DOM changed.
    await vi.waitFor(() => expect(reload).toHaveBeenCalledTimes(1));
  });

  it("does not wait for a dialog whose fields are empty", () => {
    dialog("");
    noteServerVersion(SERVER);
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("keeps the banner (and does not reload) while the typed dialog stays open", async () => {
    dialog("L4736");
    noteServerVersion(SERVER);
    noteServerVersion(SERVER);
    await Promise.resolve();
    expect(reload).not.toHaveBeenCalled();
  });
});

describe("service worker update checks", () => {
  function register() {
    const registration = { update: vi.fn(async () => {}) };
    startUpdates((options) => {
      options.onRegisteredSW?.("/sw.js", registration);
      return async () => {};
    });
    return registration;
  }

  it("asks for a new worker every ten minutes", () => {
    vi.useFakeTimers();
    const registration = register();
    expect(registration.update).not.toHaveBeenCalled();
    vi.advanceTimersByTime(UPDATE_CHECK_INTERVAL_MS - 1);
    expect(registration.update).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(registration.update).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(UPDATE_CHECK_INTERVAL_MS);
    expect(registration.update).toHaveBeenCalledTimes(2);
  });

  it("asks when the window gets focus", () => {
    const registration = register();
    window.dispatchEvent(new Event("focus"));
    expect(registration.update).toHaveBeenCalledTimes(1);
  });

  it("survives a failing update check", async () => {
    const registration = { update: vi.fn(async () => Promise.reject(new Error("offline"))) };
    startUpdates((options) => {
      options.onRegisteredSW?.("/sw.js", registration);
      return async () => {};
    });
    window.dispatchEvent(new Event("focus"));
    await Promise.resolve();
    expect(registration.update).toHaveBeenCalled();
  });
});

describe("build version", () => {
  it("is the version the bundle was built with", () => {
    expect(BUILD_VERSION).toBe("0.0.0-dev");
  });
});
