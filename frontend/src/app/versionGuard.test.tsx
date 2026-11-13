import { act, render, renderHook, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { apiFetch } from "../api/client";
import { mockApi } from "../features/test-api";
import { renderApp } from "../test-utils";
import {
  UPDATE_CHECK_INTERVAL_MS,
  WORKER_WAIT_MS,
  applyUpdate,
  noteServerVersion,
  resetUpdatesForTest,
  setVersionCheckForTest,
  startUpdates,
  useNeedRefresh,
  useUpdating,
} from "./updates";

// A page built for 1.5.0 talking to a hub that reports 1.6.0 (#288).
const BUILT_FOR = "1.5.0";
const SERVER = "1.6.0";
const BANNER = "New version available";

let reload: Mock<() => void>;
// Whether the told worker takes over the page (`controllerchange`); by default it does at once.
let controllerChanges: Mock<(ms: number) => Promise<boolean>>;

beforeEach(() => {
  reload = vi.fn<() => void>();
  controllerChanges = vi.fn<(ms: number) => Promise<boolean>>(async () => true);
  setVersionCheckForTest({ buildVersion: BUILT_FOR, reload, controllerChanges });
});

afterEach(() => {
  resetUpdatesForTest();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

/** A service worker registration whose `update()` installs a new worker after `installAfterMs` (never when null). */
function setupWorker(installAfterMs: number | null, options: { updateFails?: boolean; unregister?: () => Promise<boolean> } = {}) {
  const updateSW = vi.fn(async (reloadPage?: boolean): Promise<void> => void reloadPage);
  let needRefresh!: () => void;
  const registration = {
    update: vi.fn(async () => {
      if (options.updateFails) throw new Error("offline");
      if (installAfterMs !== null) setTimeout(() => needRefresh(), installAfterMs);
    }),
    unregister: vi.fn(options.unregister ?? (async () => true)),
  };
  startUpdates((o) => {
    needRefresh = o.onNeedRefresh;
    o.onRegisteredSW?.("/sw.js", registration);
    return updateSW;
  });
  return { updateSW, registration, needRefresh: () => needRefresh() };
}

describe("version mismatch shows the banner and does nothing else", () => {
  it("shows the banner and never reloads by itself", async () => {
    mockApi({});
    await renderApp({ path: "/" });
    expect(screen.queryByText(BANNER)).toBeNull();
    await act(async () => noteServerVersion(SERVER));
    await act(async () => noteServerVersion(SERVER));
    expect(screen.getByText(BANNER)).toBeVisible();
    expect(screen.getByRole("main")).toBeVisible();
    expect(reload).not.toHaveBeenCalled();
  });

  it("does nothing while the versions are equal or the hub names none", async () => {
    mockApi({});
    await renderApp({ path: "/" });
    await act(async () => {
      noteServerVersion(BUILT_FOR);
      noteServerVersion(null);
      noteServerVersion(undefined);
      noteServerVersion("");
    });
    expect(screen.queryByText(BANNER)).toBeNull();
    expect(reload).not.toHaveBeenCalled();
  });

  it("takes the banner down again when the hub reports the bundle's version", async () => {
    const { result } = renderHook(() => useNeedRefresh());
    act(() => noteServerVersion(SERVER));
    expect(result.current).toBe(true);
    act(() => noteServerVersion(BUILT_FOR));
    expect(result.current).toBe(false);
  });

  it("leaves a dialog with typed input alone", async () => {
    render(
      <div role="dialog" aria-label="Add sheet">
        <input aria-label="Code" defaultValue="L4736" />
      </div>,
    );
    noteServerVersion(SERVER);
    await Promise.resolve();
    expect(reload).not.toHaveBeenCalled();
    expect(screen.getByRole("textbox", { name: "Code" })).toHaveValue("L4736");
  });

  it("reads the version from the header of an API response, errors included", async () => {
    const { result } = renderHook(() => useNeedRefresh());
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 200, headers: { "Content-Type": "application/json", "X-Hub-Version": SERVER } })));
    await apiFetch("/api/v1/info");
    expect(result.current).toBe(true);
    act(() => noteServerVersion(BUILT_FOR));
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 404, headers: { "X-Hub-Version": SERVER } })));
    await expect(apiFetch("/api/v1/nope")).rejects.toThrow();
    expect(result.current).toBe(true);
  });

  it("asks the browser for the new worker at once, once per version", () => {
    const { registration } = setupWorker(null);
    noteServerVersion(SERVER);
    noteServerVersion(SERVER);
    expect(registration.update).toHaveBeenCalledTimes(1);
    noteServerVersion("1.7.0");
    expect(registration.update).toHaveBeenCalledTimes(2);
  });
});

describe("the Reload button ends on the new bundle", () => {
  beforeEach(() => vi.useFakeTimers());

  it("applies a worker that already waits and reloads once on its takeover (no update call, no unregister)", async () => {
    const { updateSW, registration, needRefresh } = setupWorker(null);
    needRefresh();
    await applyUpdate();
    expect(updateSW).toHaveBeenCalledWith(true);
    expect(registration.update).not.toHaveBeenCalled();
    expect(registration.unregister).not.toHaveBeenCalled();
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("without a waiting worker: updates, waits for the install, applies it, and reloads on its takeover", async () => {
    const { updateSW, registration } = setupWorker(1_000);
    const done = applyUpdate();
    await vi.advanceTimersByTimeAsync(0);
    expect(registration.update).toHaveBeenCalledTimes(1);
    expect(updateSW).not.toHaveBeenCalled();
    expect(reload).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1_000);
    await done;
    expect(updateSW).toHaveBeenCalledWith(true);
    expect(registration.unregister).not.toHaveBeenCalled();
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("waits for the told worker to take over, then reloads the page itself", async () => {
    const { updateSW, registration, needRefresh } = setupWorker(null);
    needRefresh();
    await applyUpdate();
    expect(controllerChanges).toHaveBeenCalledWith(WORKER_WAIT_MS);
    // Listening starts before the worker is told, so a fast takeover is not missed.
    expect(controllerChanges.mock.invocationCallOrder[0]).toBeLessThan(updateSW.mock.invocationCallOrder[0] ?? 0);
    expect(registration.unregister).not.toHaveBeenCalled();
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("a page registered without a controller (first visit, or after the fallback): the takeover comes and the page reloads once", async () => {
    // vite-plugin-pwa reloads on the takeover only when a worker controlled the page at registration (isUpdate);
    // here its updateSW only tells the worker and nothing else reloads.
    const updateSW = vi.fn(async (reloadPage?: boolean): Promise<void> => void reloadPage);
    let needRefresh!: () => void;
    const registration = { update: vi.fn(async () => {}), unregister: vi.fn(async () => true) };
    startUpdates((o) => {
      needRefresh = o.onNeedRefresh;
      o.onRegisteredSW?.("/sw.js", registration);
      return updateSW;
    });
    let takeOver!: (changed: boolean) => void;
    controllerChanges.mockImplementation(() => new Promise((resolve) => (takeOver = resolve)));
    needRefresh();
    const done = applyUpdate();
    await vi.advanceTimersByTimeAsync(100);
    expect(reload).not.toHaveBeenCalled();
    takeOver(true);
    await done;
    expect(reload).toHaveBeenCalledTimes(1);
    expect(registration.unregister).not.toHaveBeenCalled();
  });

  it("a worker that does not take over in time (the old one kept busy): removes the old registration, then reloads", async () => {
    // Chromium holds the new worker back while the old one has work, e.g. a request of the page.
    controllerChanges.mockImplementation((ms) => new Promise((resolve) => setTimeout(() => resolve(false), ms)));
    const { updateSW, registration, needRefresh } = setupWorker(null);
    needRefresh();
    const done = applyUpdate();
    await vi.advanceTimersByTimeAsync(WORKER_WAIT_MS - 1);
    expect(updateSW).toHaveBeenCalledWith(true);
    expect(registration.unregister).not.toHaveBeenCalled();
    expect(reload).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    await done;
    expect(registration.unregister).toHaveBeenCalledTimes(1);
    expect(reload).toHaveBeenCalledTimes(1);
    expect(registration.unregister.mock.invocationCallOrder[0]).toBeLessThan(reload.mock.invocationCallOrder[0] ?? 0);
  });

  it("the same after an update the button asked for itself", async () => {
    controllerChanges.mockImplementation((ms) => new Promise((resolve) => setTimeout(() => resolve(false), ms)));
    const { updateSW, registration } = setupWorker(200);
    const done = applyUpdate();
    await vi.advanceTimersByTimeAsync(200 + WORKER_WAIT_MS);
    await done;
    expect(updateSW).toHaveBeenCalledWith(true);
    expect(registration.unregister).toHaveBeenCalledTimes(1);
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("an unregister that fails or never answers still ends in the reload, within the budget", async () => {
    controllerChanges.mockImplementation(async () => false);
    const failing = setupWorker(null, { unregister: async () => Promise.reject(new Error("gone")) });
    failing.needRefresh();
    await applyUpdate();
    expect(reload).toHaveBeenCalledTimes(1);

    resetUpdatesForTest();
    setVersionCheckForTest({ buildVersion: BUILT_FOR, reload, controllerChanges });
    const hanging = setupWorker(null, { unregister: () => new Promise<never>(() => {}) });
    hanging.needRefresh();
    const done = applyUpdate();
    await vi.advanceTimersByTimeAsync(WORKER_WAIT_MS - 1);
    expect(reload).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    await done;
    expect(reload).toHaveBeenCalledTimes(2);
  });

  it("with the browser's own signal: a controllerchange ends the wait, without one it gives up after the budget", async () => {
    const container = new EventTarget();
    Object.defineProperty(navigator, "serviceWorker", { value: container, configurable: true });
    const removed = vi.spyOn(container, "removeEventListener");
    try {
      resetUpdatesForTest();
      setVersionCheckForTest({ buildVersion: BUILT_FOR, reload });
      const taking = setupWorker(null);
      taking.needRefresh();
      const done = applyUpdate();
      await vi.advanceTimersByTimeAsync(100);
      container.dispatchEvent(new Event("controllerchange"));
      await done;
      expect(taking.registration.unregister).not.toHaveBeenCalled();
      expect(reload).toHaveBeenCalledTimes(1);
      expect(removed).toHaveBeenCalledWith("controllerchange", expect.any(Function));

      // The next page: a fresh module state.
      resetUpdatesForTest();
      reload.mockClear();
      setVersionCheckForTest({ buildVersion: BUILT_FOR, reload });
      const stuck = setupWorker(null);
      stuck.needRefresh();
      const second = applyUpdate();
      await vi.advanceTimersByTimeAsync(WORKER_WAIT_MS);
      await second;
      expect(stuck.registration.unregister).toHaveBeenCalledTimes(1);
      expect(reload).toHaveBeenCalledTimes(1);
      // A late takeover after giving up changes nothing.
      container.dispatchEvent(new Event("controllerchange"));
      expect(reload).toHaveBeenCalledTimes(1);
    } finally {
      delete (navigator as unknown as Record<string, unknown>).serviceWorker;
    }
  });

  it("without a service worker container there is no takeover to wait for: removes the registration and reloads", async () => {
    expect("serviceWorker" in navigator).toBe(false);
    resetUpdatesForTest();
    setVersionCheckForTest({ buildVersion: BUILT_FOR, reload });
    const { registration, needRefresh } = setupWorker(null);
    needRefresh();
    await applyUpdate();
    expect(registration.unregister).toHaveBeenCalledTimes(1);
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("the hub answered but no new worker came in time (slow install): removes the registration, then reloads", async () => {
    // A plain reload here would be answered by the old worker with the old shell from its precache.
    const { updateSW, registration } = setupWorker(null);
    const done = applyUpdate();
    await vi.advanceTimersByTimeAsync(WORKER_WAIT_MS - 1);
    expect(reload).not.toHaveBeenCalled();
    expect(registration.unregister).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    await done;
    expect(registration.unregister).toHaveBeenCalledTimes(1);
    expect(reload).toHaveBeenCalledTimes(1);
    expect(registration.unregister.mock.invocationCallOrder[0]).toBeLessThan(reload.mock.invocationCallOrder[0] ?? 0);
    expect(updateSW).not.toHaveBeenCalled();
  });

  it("the same with an unregister that never answers: the reload follows within its own budget", async () => {
    const { registration } = setupWorker(null, { unregister: () => new Promise<never>(() => {}) });
    const done = applyUpdate();
    await vi.advanceTimersByTimeAsync(WORKER_WAIT_MS);
    expect(registration.unregister).toHaveBeenCalledTimes(1);
    expect(reload).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(WORKER_WAIT_MS);
    await done;
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("a failed check (hub unreachable) keeps the registration and reloads on the old shell", async () => {
    const { registration } = setupWorker(null, { updateFails: true });
    const done = applyUpdate();
    await vi.advanceTimersByTimeAsync(WORKER_WAIT_MS);
    await done;
    expect(registration.unregister).not.toHaveBeenCalled();
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("reloads at once without a service worker (dev server, unsupported browser)", async () => {
    await applyUpdate();
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("reloads once: a takeover after the budget, and presses after the reload, do not reload again", async () => {
    const container = new EventTarget();
    Object.defineProperty(navigator, "serviceWorker", { value: container, configurable: true });
    try {
      resetUpdatesForTest();
      setVersionCheckForTest({ buildVersion: BUILT_FOR, reload });
      const { updateSW, registration, needRefresh } = setupWorker(null);
      needRefresh();
      const done = applyUpdate();
      await vi.advanceTimersByTimeAsync(WORKER_WAIT_MS);
      await done;
      expect(reload).toHaveBeenCalledTimes(1);
      // The takeover comes late, while the page is already going.
      container.dispatchEvent(new Event("controllerchange"));
      await vi.advanceTimersByTimeAsync(WORKER_WAIT_MS * 2);
      expect(reload).toHaveBeenCalledTimes(1);
      // A press after the reload decision is ignored: nothing is told, removed or reloaded again.
      await applyUpdate();
      await vi.advanceTimersByTimeAsync(WORKER_WAIT_MS * 2);
      expect(updateSW).toHaveBeenCalledTimes(1);
      expect(registration.unregister).toHaveBeenCalledTimes(1);
      expect(reload).toHaveBeenCalledTimes(1);
    } finally {
      delete (navigator as unknown as Record<string, unknown>).serviceWorker;
    }
  });

  it("does not take a second press between the reload decision and the navigation", async () => {
    const { result } = renderHook(() => useUpdating());
    const { updateSW, registration, needRefresh } = setupWorker(null, { unregister: () => new Promise<never>(() => {}) });
    controllerChanges.mockImplementation(async () => false);
    needRefresh();
    const done = applyUpdate();
    await vi.advanceTimersByTimeAsync(0);
    // Removing the registration: a press now is ignored.
    void applyUpdate();
    await vi.advanceTimersByTimeAsync(WORKER_WAIT_MS);
    await done;
    expect(reload).toHaveBeenCalledTimes(1);
    expect(result.current).toBe(true);
    // And after the reload, until the page goes.
    await applyUpdate();
    await vi.advanceTimersByTimeAsync(WORKER_WAIT_MS * 3);
    expect(updateSW).toHaveBeenCalledTimes(1);
    expect(registration.unregister).toHaveBeenCalledTimes(1);
    expect(reload).toHaveBeenCalledTimes(1);
    expect(result.current).toBe(true);
  });

  it("ignores a second click while the first is under way", async () => {
    const { updateSW } = setupWorker(500);
    const first = applyUpdate();
    void applyUpdate();
    await vi.advanceTimersByTimeAsync(500);
    await first;
    expect(updateSW).toHaveBeenCalledTimes(1);
  });

  it("can be pressed again when the worker could not take over", async () => {
    const { updateSW, needRefresh } = setupWorker(null);
    needRefresh();
    updateSW.mockRejectedValueOnce(new Error("no controller"));
    await applyUpdate();
    expect(reload).not.toHaveBeenCalled();
    await applyUpdate();
    expect(updateSW).toHaveBeenCalledTimes(2);
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("an update() that never answers is given up on within the budget, then the plain reload", async () => {
    const updateSW = vi.fn(async (reloadPage?: boolean): Promise<void> => void reloadPage);
    const registration = { update: vi.fn(() => new Promise<never>(() => {})) };
    startUpdates((o) => (o.onRegisteredSW?.("/sw.js", registration), updateSW));
    const done = applyUpdate();
    await vi.advanceTimersByTimeAsync(WORKER_WAIT_MS - 1);
    expect(reload).not.toHaveBeenCalled();
    // The check used its budget; the wait for a worker has its own: both are bounded.
    await vi.advanceTimersByTimeAsync(1);
    expect(reload).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(WORKER_WAIT_MS);
    await done;
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("is pending while it works and stays so once the page reloads; not before, and not after a failure", async () => {
    const { result } = renderHook(() => useUpdating());
    const { needRefresh } = setupWorker(1_000);
    expect(result.current).toBe(false);
    const done = applyUpdate();
    await vi.advanceTimersByTimeAsync(0);
    expect(result.current).toBe(true);
    await vi.advanceTimersByTimeAsync(1_000);
    await done;
    expect(reload).toHaveBeenCalledTimes(1);
    // The page is going: the button stays busy until the navigation replaces it.
    expect(result.current).toBe(true);

    // Failure: the worker cannot take over.
    resetUpdatesForTest();
    setVersionCheckForTest({ buildVersion: BUILT_FOR, reload });
    const failing = setupWorker(null);
    failing.updateSW.mockRejectedValueOnce(new Error("no controller"));
    failing.needRefresh();
    const second = applyUpdate();
    await vi.advanceTimersByTimeAsync(0);
    await second;
    expect(result.current).toBe(false);
    void needRefresh;
  });

  it("marks the button busy and says Updating… while it works, announced, with focus kept on it", async () => {
    vi.useRealTimers();
    setupWorker(300);
    mockApi({});
    await renderApp({ path: "/" });
    await act(async () => noteServerVersion(SERVER));
    const button = screen.getByRole("button", { name: "Reload" });
    expect(button).not.toHaveAttribute("aria-disabled", "true");
    button.focus();
    await act(async () => button.click());
    const busy = screen.getByRole("button", { name: "Updating…" });
    // Not `disabled`: a disabled button drops the focus to the page, and the person loses their place.
    expect(busy).toBe(button);
    expect(busy).toBeEnabled();
    expect(busy).toHaveAttribute("aria-disabled", "true");
    expect(document.activeElement).toBe(busy);
    // The label change alone is not read out; the status region next to it says it.
    expect(screen.getByRole("status")).toHaveTextContent("Updating…");
    // Once the page reloads, the button stays busy until the navigation replaces the page.
    await vi.waitFor(() => expect(reload).toHaveBeenCalledTimes(1));
    expect(screen.getByRole("button", { name: "Updating…" })).toHaveAttribute("aria-disabled", "true");
    expect(screen.getByRole("status")).toHaveTextContent("Updating…");
  });

  it("a press while it works does nothing", async () => {
    vi.useRealTimers();
    const { updateSW } = setupWorker(300);
    mockApi({});
    await renderApp({ path: "/" });
    await act(async () => noteServerVersion(SERVER));
    const button = screen.getByRole("button", { name: "Reload" });
    await act(async () => button.click());
    await act(async () => button.click());
    await vi.waitFor(() => expect(reload).toHaveBeenCalledTimes(1));
    expect(updateSW).toHaveBeenCalledTimes(1);
  });

  it("an update() that throws at once still ends in the plain reload", async () => {
    const updateSW = vi.fn(async (reloadPage?: boolean): Promise<void> => void reloadPage);
    const registration = {
      update: vi.fn((): Promise<void> => {
        throw new Error("InvalidStateError");
      }),
    };
    startUpdates((o) => (o.onRegisteredSW?.("/sw.js", registration), updateSW));
    const done = applyUpdate();
    await vi.advanceTimersByTimeAsync(WORKER_WAIT_MS);
    await done;
    expect(registration.update).toHaveBeenCalledTimes(1);
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("the banner's button runs this path", async () => {
    vi.useRealTimers();
    const { updateSW, registration } = setupWorker(100);
    mockApi({});
    await renderApp({ path: "/" });
    await act(async () => noteServerVersion(SERVER));
    await act(async () => screen.getByRole("button", { name: "Reload" }).click());
    await vi.waitFor(() => expect(reload).toHaveBeenCalledTimes(1));
    expect(updateSW).toHaveBeenCalledWith(true);
    expect(registration.update).toHaveBeenCalled();
  });
});

describe("service worker update checks", () => {
  it("asks for a new worker every ten minutes and when the window gets focus", () => {
    vi.useFakeTimers();
    const { registration } = setupWorker(null);
    vi.advanceTimersByTime(UPDATE_CHECK_INTERVAL_MS - 1);
    expect(registration.update).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(registration.update).toHaveBeenCalledTimes(1);
    window.dispatchEvent(new Event("focus"));
    expect(registration.update).toHaveBeenCalledTimes(2);
  });

  it("keeps asking after failed attempts and handles every rejection (the hub is down for a while)", async () => {
    vi.useFakeTimers();
    const attempts: Promise<unknown>[] = [];
    const registration = {
      update: vi.fn(() => {
        const failed = Promise.reject(new Error("offline"));
        // Calling catch is what marks a rejection as handled.
        vi.spyOn(failed, "catch");
        attempts.push(failed);
        return failed;
      }),
    };
    startUpdates((o) => (o.onRegisteredSW?.("/sw.js", registration), async () => {}));
    for (let i = 0; i < 4; i++) await vi.advanceTimersByTimeAsync(UPDATE_CHECK_INTERVAL_MS);
    window.dispatchEvent(new Event("focus"));
    expect(registration.update).toHaveBeenCalledTimes(5);
    for (const failed of attempts) expect(failed.catch).toHaveBeenCalled();
  });

  it("survives an update() that throws instead of rejecting", () => {
    vi.useFakeTimers();
    const registration = {
      update: vi.fn(() => {
        throw new Error("sync");
      }),
    };
    startUpdates((o) => (o.onRegisteredSW?.("/sw.js", registration as never), async () => {}));
    expect(() => vi.advanceTimersByTime(UPDATE_CHECK_INTERVAL_MS * 2)).not.toThrow();
    expect(registration.update).toHaveBeenCalledTimes(2);
  });

  it("a second startUpdates does not stack a focus listener or a timer", () => {
    vi.useFakeTimers();
    const first = { update: vi.fn(async () => {}) };
    const second = { update: vi.fn(async () => {}) };
    startUpdates((o) => (o.onRegisteredSW?.("/sw.js", first), async () => {}));
    startUpdates((o) => (o.onRegisteredSW?.("/sw.js", second), async () => {}));
    window.dispatchEvent(new Event("focus"));
    vi.advanceTimersByTime(UPDATE_CHECK_INTERVAL_MS);
    expect(first.update).not.toHaveBeenCalled();
    expect(second.update).toHaveBeenCalledTimes(2);
  });
});
