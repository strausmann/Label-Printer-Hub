import { useSyncExternalStore } from "react";

/** The version this bundle was built for (`HUB_VERSION` at build time, see vite.config.ts). */
declare const __HUB_BUILD_VERSION__: string;
export const BUILD_VERSION: string = typeof __HUB_BUILD_VERSION__ === "string" ? __HUB_BUILD_VERSION__ : "0.0.0-dev";

/** The part of a service worker registration we use. */
export interface SwRegistration {
  update: () => Promise<unknown>;
}

/** What `registerSW` from vite-plugin-pwa looks like to us (so tests can stand in for it). */
export type RegisterSW = (options: {
  onNeedRefresh: () => void;
  onRegisteredSW?: (swUrl: string, registration: SwRegistration | undefined) => void;
}) => (reloadPage?: boolean) => Promise<void>;

/** How often an open tab asks for a new service worker (it also asks whenever the window gets focus). */
export const UPDATE_CHECK_INTERVAL_MS = 10 * 60 * 1000;
/** How long the Reload button waits for a new service worker to install before it falls back to a plain reload. */
export const WORKER_WAIT_MS = 5_000;

// A new service worker waits for the person (see pwa.config.ts); true while one does.
let waitingWorker = false;
// The hub runs another version than this bundle.
let versionMismatch = false;
let refreshing = false;
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

/**
 * The banner's button. Applies a waiting worker (it takes over and the page reloads on the new
 * files); without one it asks the browser for one and waits, bounded and on the outcome (a worker
 * that starts waiting), before it applies it. Only when none comes does it reload, because a plain
 * reload alone is answered from the old precache.
 */
export async function applyUpdate(): Promise<void> {
  if (refreshing) return;
  refreshing = true;
  updating = true;
  emit();
  try {
    if (!waitingWorker && registration) {
      // The check itself is bounded too: a network that swallows the request must not keep the button busy.
      await withinBudget(registration.update(), deps.workerWaitMs);
      await workerWaits(deps.workerWaitMs);
    }
    if (waitingWorker && updateSW) await updateSW(true);
    else deps.reload();
  } catch {
    // The worker could not take over: the banner stays and the button can be pressed again.
  } finally {
    refreshing = false;
    updating = false;
    emit();
  }
}

/** Waits for `work` for at most `ms`; its failure (offline, file gone) or a timeout is not an error here. */
async function withinBudget(work: Promise<unknown>, ms: number): Promise<void> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    await Promise.race([work, new Promise<void>((resolve) => (timer = setTimeout(resolve, ms)))]);
  } catch {
    // The bounded wait for a worker that follows decides.
  } finally {
    clearTimeout(timer);
  }
}

/** What the version check needs from the page (tests replace it). */
const deps = {
  buildVersion: BUILD_VERSION,
  workerWaitMs: WORKER_WAIT_MS,
  reload: () => window.location.reload(),
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
  updating = false;
  updateSW = null;
  registration = null;
  checkedFor = null;
  stopUpdateChecks?.();
  workerWaiters.clear();
  deps.workerWaitMs = WORKER_WAIT_MS;
  deps.buildVersion = BUILD_VERSION;
  deps.reload = () => window.location.reload();
  emit();
}

export function setVersionCheckForTest(overrides: { buildVersion?: string; reload?: () => void; workerWaitMs?: number }): void {
  if (overrides.workerWaitMs !== undefined) deps.workerWaitMs = overrides.workerWaitMs;
  if (overrides.buildVersion !== undefined) deps.buildVersion = overrides.buildVersion;
  if (overrides.reload) deps.reload = overrides.reload;
}
