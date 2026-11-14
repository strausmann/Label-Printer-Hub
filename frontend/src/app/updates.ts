// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useSyncExternalStore } from "react";

/** The version this bundle was built for (`HUB_VERSION` at build time, see vite.config.ts). */
declare const __HUB_BUILD_VERSION__: string;
export const BUILD_VERSION: string = typeof __HUB_BUILD_VERSION__ === "string" ? __HUB_BUILD_VERSION__ : "0.0.0-dev";

/** The part of a service worker registration we use. */
export interface SwRegistration {
  update: () => Promise<unknown>;
  unregister?: () => Promise<boolean>;
}

/** What `registerSW` from vite-plugin-pwa looks like to us (so tests can stand in for it). */
export type RegisterSW = (options: {
  onNeedRefresh: () => void;
  onRegisteredSW?: (swUrl: string, registration: SwRegistration | undefined) => void;
}) => (reloadPage?: boolean) => Promise<void>;

/** How often an open tab asks for a new service worker (it also asks whenever the window gets focus). */
export const UPDATE_CHECK_INTERVAL_MS = 10 * 60 * 1000;
/**
 * How long the Reload button waits for a new service worker to install before it falls back to a plain reload,
 * and how long it waits for a told worker to take over the page before it removes the old one.
 */
export const WORKER_WAIT_MS = 5_000;

// A new service worker waits for the person (see pwa.config.ts); true while one does.
let waitingWorker = false;
// The hub runs another version than this bundle.
let versionMismatch = false;
let refreshing = false;
// The page was told to reload: the button stays busy (and takes no press) until the page goes.
let reloading = false;
// The Reload button was pressed and the page is still getting the new version (the button shows "Updating…").
let updating = false;
let updateSW: ((reloadPage?: boolean) => Promise<void>) | null = null;
let registration: SwRegistration | null = null;
let stopUpdateChecks: (() => void) | null = null;
// The newest server version the browser was already asked to fetch a worker for.
let checkedFor: string | null = null;
// Called when a worker starts waiting; the Reload button waits for it with a time limit.
const workerWaiters = new Set<() => void>();
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());

/**
 * Starts the service worker. A new version waits (it is not forced on open tabs, whose lazy
 * files would be gone) until the person chooses to reload; then the banner shows.
 * Calling it again replaces the earlier registration (no second focus listener or timer).
 */
export function startUpdates(register: RegisterSW): void {
  stopUpdateChecks?.();
  updateSW = register({
    onNeedRefresh() {
      waitingWorker = true;
      emit();
      workerWaiters.forEach((wake) => wake());
    },
    onRegisteredSW(_swUrl, reg) {
      if (!reg) return;
      registration = reg;
      scheduleUpdateChecks(reg);
    },
  });
}

/** Asks for a new worker; a failure (offline, hub restarting) is normal and must never stop the checks. */
function checkForWorker(reg: SwRegistration): void {
  try {
    void reg.update().catch(() => {});
  } catch {
    // update() threw before it returned a promise.
  }
}

/**
 * The browser looks for a new service worker on navigation only; a tab that stays open for days
 * never would. Ask when the window gets focus and every few minutes, also after failed attempts
 * (the hub may be down for a while during an update).
 */
function scheduleUpdateChecks(reg: SwRegistration): void {
  const check = () => checkForWorker(reg);
  window.addEventListener("focus", check);
  const timer = window.setInterval(check, UPDATE_CHECK_INTERVAL_MS);
  stopUpdateChecks = () => {
    window.removeEventListener("focus", check);
    window.clearInterval(timer);
    stopUpdateChecks = null;
  };
}

/** Resolves true as soon as a worker waits, false after `ms`. */
function workerWaits(ms: number): Promise<boolean> {
  if (waitingWorker) return Promise.resolve(true);
  return new Promise((resolve) => {
    const finish = (waits: boolean) => {
      clearTimeout(timer);
      workerWaiters.delete(wake);
      resolve(waits);
    };
    const wake = () => finish(true);
    const timer = setTimeout(() => finish(false), ms);
    workerWaiters.add(wake);
  });
}

/** Resolves true when another service worker takes control of this page, false after `ms`. */
function controllerChanges(ms: number): Promise<boolean> {
  const container = typeof navigator === "undefined" ? undefined : navigator.serviceWorker;
  if (!container) return Promise.resolve(false);
  return new Promise((resolve) => {
    const finish = (changed: boolean) => {
      clearTimeout(timer);
      container.removeEventListener("controllerchange", onChange);
      resolve(changed);
    };
    const onChange = () => finish(true);
    const timer = setTimeout(() => finish(false), ms);
    container.addEventListener("controllerchange", onChange);
  });
}

/**
 * The banner's button. Applies a waiting worker (it takes over and the page reloads on the new
 * files); without one it asks the browser for one and waits, bounded and on the outcome (a worker
 * that starts waiting), before it applies it. Only when none comes does it reload, because a plain
 * reload alone is answered from the old precache.
 *
 * Telling the waiting worker to skip waiting is not enough on its own: Chromium activates it only once
 * the old worker has no work left, and a request the page sends at that moment (a status poll, a refetch
 * on focus) restarts the old worker and can hold the new one back for minutes. So the button waits for
 * the takeover (`controllerchange`), bounded, and then reloads itself (vite-plugin-pwa reloads on the
 * takeover only when a worker controlled the page at registration, which is not so on a first visit or
 * after the fallback below). When the takeover does not come, or no worker turns up in time although
 * the hub answered the check, it removes the old registration and reloads, so the hub answers the page
 * with the new version and the new bundle registers its worker. A failed check (hub unreachable) keeps
 * the registration: the old shell from the precache is better than no page at all.
 *
 * The page reloads once per press, and from then on the button stays busy until the page goes.
 */
export async function applyUpdate(): Promise<void> {
  // `refreshing` stays set once the page reloads, so it reloads once per page.
  if (refreshing) return;
  refreshing = true;
  updating = true;
  emit();
  try {
    let hubAnswered = false;
    if (!waitingWorker && registration) {
      // The check itself is bounded too: a network that swallows the request must not keep the button busy.
      // Called inside a promise: an update() that throws at once (an invalid state of the
      // registration) is a failed check like any other, not a reason to skip the reload below.
      const reg = registration;
      hubAnswered = await withinBudget(Promise.resolve().then(() => reg.update()), deps.workerWaitMs);
      await workerWaits(deps.workerWaitMs);
    }
    if (waitingWorker && updateSW) {
      // Listen before the worker is told, so a fast takeover is not missed.
      const takenOver = deps.controllerChanges(deps.workerWaitMs);
      await updateSW(true);
      if (await takenOver) {
        startReload();
        return;
      }
      await removeRegistration();
      startReload();
    } else {
      // No worker in time: a plain reload would be answered by the old worker from its precache.
      if (hubAnswered) await removeRegistration();
      startReload();
    }
  } catch {
    // The worker could not take over: the banner stays and the button can be pressed again.
  } finally {
    if (!reloading) {
      refreshing = false;
      updating = false;
      emit();
    }
  }
}

/**
 * Reloads the page and keeps the button busy until it goes. A takeover after the budget cannot reload a
 * second time: `controllerChanges` has settled and removed its listener by then.
 */
function startReload(): void {
  reloading = true;
  deps.reload();
}

/** Removes the service worker registration, bounded; a failure is not an error here (the reload follows). */
async function removeRegistration(): Promise<void> {
  const reg = registration;
  if (reg?.unregister) await withinBudget(Promise.resolve().then(() => reg.unregister?.()), deps.workerWaitMs);
}

/**
 * Waits for `work` for at most `ms`; its failure (offline, file gone) or a timeout is not an error here.
 * Resolves true when `work` settled successfully within the time.
 */
async function withinBudget(work: Promise<unknown>, ms: number): Promise<boolean> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([work.then(() => true), new Promise<boolean>((resolve) => (timer = setTimeout(() => resolve(false), ms)))]);
  } catch {
    // The bounded wait for a worker that follows decides.
    return false;
  } finally {
    clearTimeout(timer);
  }
}

/** What the version check needs from the page (tests replace it). */
const deps = {
  buildVersion: BUILD_VERSION,
  workerWaitMs: WORKER_WAIT_MS,
  reload: () => window.location.reload(),
  controllerChanges,
};

/**
 * Called with the version the hub reports (the `X-Hub-Version` header of an API response, the
 * `hello` frame of the event stream, which follows every reconnect). A page built for another
 * version shows the "New version available" banner; the person reloads (no automatic reload, so
 * nothing typed is lost). The browser is asked for the new service worker at once, so that the
 * button usually finds it waiting.
 */
export function noteServerVersion(serverVersion: string | null | undefined): void {
  if (!serverVersion) return;
  if (serverVersion === deps.buildVersion) {
    checkedFor = null;
    if (versionMismatch) {
      versionMismatch = false;
      emit();
    }
    return;
  }
  if (!versionMismatch) {
    versionMismatch = true;
    emit();
  }
  if (checkedFor !== serverVersion && registration) {
    checkedFor = serverVersion;
    checkForWorker(registration);
  }
}

export function useUpdating(): boolean {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => updating,
  );
}

export function useNeedRefresh(): boolean {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => waitingWorker || versionMismatch,
  );
}

export function resetUpdatesForTest(): void {
  waitingWorker = false;
  versionMismatch = false;
  refreshing = false;
  reloading = false;
  updating = false;
  updateSW = null;
  registration = null;
  checkedFor = null;
  stopUpdateChecks?.();
  workerWaiters.clear();
  deps.workerWaitMs = WORKER_WAIT_MS;
  deps.buildVersion = BUILD_VERSION;
  deps.reload = () => window.location.reload();
  deps.controllerChanges = controllerChanges;
  emit();
}

export function setVersionCheckForTest(overrides: {
  buildVersion?: string;
  reload?: () => void;
  workerWaitMs?: number;
  controllerChanges?: (ms: number) => Promise<boolean>;
}): void {
  if (overrides.controllerChanges) deps.controllerChanges = overrides.controllerChanges;
  if (overrides.workerWaitMs !== undefined) deps.workerWaitMs = overrides.workerWaitMs;
  if (overrides.buildVersion !== undefined) deps.buildVersion = overrides.buildVersion;
  if (overrides.reload) deps.reload = overrides.reload;
}
