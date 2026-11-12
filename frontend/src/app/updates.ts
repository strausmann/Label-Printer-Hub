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
/** `sessionStorage` key: the server version the page already reloaded for (loop guard). */
export const RELOAD_GUARD_KEY = "hub.reloaded-for-version";

// A new service worker waits for the person (see pwa.config.ts); true while one does.
let waitingWorker = false;
// The server runs another version than this bundle and the page did not (or could not) fix that by reloading.
let versionBanner = false;
let reloading = false;
let updateSW: ((reloadPage?: boolean) => Promise<void>) | null = null;
let stopWatchingDialogs: (() => void) | null = null;
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());

/**
 * Starts the service worker. A new version waits (it is not forced on open tabs, whose lazy
 * files would be gone) until the person chooses to reload; then `needRefresh` turns true.
 */
export function startUpdates(register: RegisterSW): void {
  updateSW = register({
    onNeedRefresh() {
      waitingWorker = true;
      emit();
    },
    onRegisteredSW(_swUrl, registration) {
      if (registration) scheduleUpdateChecks(registration);
    },
  });
}

/**
 * The browser looks for a new service worker on navigation only; a tab that stays open for days
 * never would. Ask when the window gets focus and every few minutes.
 */
function scheduleUpdateChecks(registration: SwRegistration): void {
  const check = () => void registration.update().catch(() => {});
  window.addEventListener("focus", check);
  window.setInterval(check, UPDATE_CHECK_INTERVAL_MS);
}

/** Activates the waiting version and reloads the page; without a waiting version it reloads. */
export function applyUpdate(): void {
  if (waitingWorker && updateSW) void updateSW(true);
  else deps.reload();
}

/** What the version check needs from the page (tests replace it). */
const deps = {
  buildVersion: BUILD_VERSION,
  reload: () => window.location.reload(),
};

const TEXT_FIELDS = "input:not([type=hidden]):not([type=checkbox]):not([type=radio]):not([type=button]):not([type=submit]), textarea";

/** A dialog is open and holds something the person typed. */
function typedDialogOpen(): boolean {
  for (const dialog of document.querySelectorAll('[role="dialog"], [role="alertdialog"], dialog[open]')) {
    for (const field of dialog.querySelectorAll<HTMLInputElement | HTMLTextAreaElement>(TEXT_FIELDS)) {
      if (field.value.trim() !== "") return true;
    }
  }
  return false;
}

function readGuard(): string | null {
  try {
    return window.sessionStorage.getItem(RELOAD_GUARD_KEY);
  } catch {
    return null;
  }
}

function writeGuard(version: string | null): void {
  try {
    if (version === null) window.sessionStorage.removeItem(RELOAD_GUARD_KEY);
    else window.sessionStorage.setItem(RELOAD_GUARD_KEY, version);
  } catch {
    // Private mode: no guard. The `reloading` flag still stops a second reload in this page.
  }
}

function showVersionBanner(): void {
  if (versionBanner) return;
  versionBanner = true;
  emit();
}

function reloadFor(serverVersion: string): void {
  if (reloading) return;
  reloading = true;
  writeGuard(serverVersion);
  if (waitingWorker && updateSW) void updateSW(true);
  else deps.reload();
}

/** Reload once the dialog with typed input is gone; the banner stays until then. */
function reloadWhenDialogCloses(serverVersion: string): void {
  if (stopWatchingDialogs) return;
  const observer = new MutationObserver(() => {
    if (typedDialogOpen()) return;
    stopWatchingDialogs?.();
    reloadFor(serverVersion);
  });
  observer.observe(document.body, { childList: true, subtree: true });
  stopWatchingDialogs = () => {
    observer.disconnect();
    stopWatchingDialogs = null;
  };
}

/**
 * Called with the version the server reports (the `X-Hub-Version` header of an API response, the
 * `hello` frame of the event stream). A page built for another version reloads once, completely,
 * so the old bundle never keeps talking to a new server (#288).
 *
 * Guards: a page that already reloaded for this version and still differs (the old service worker
 * served the old files again) shows the banner and does not reload again; a dialog with typed
 * input is not thrown away, the banner shows and the reload waits for the dialog to close.
 */
export function noteServerVersion(serverVersion: string | null | undefined): void {
  if (!serverVersion) return;
  if (serverVersion === deps.buildVersion) {
    writeGuard(null);
    if (versionBanner) {
      versionBanner = false;
      emit();
    }
    return;
  }
  if (reloading) return;
  if (readGuard() === serverVersion) return showVersionBanner();
  if (typedDialogOpen()) {
    showVersionBanner();
    return reloadWhenDialogCloses(serverVersion);
  }
  reloadFor(serverVersion);
}

export function useNeedRefresh(): boolean {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => waitingWorker || versionBanner,
  );
}

export function resetUpdatesForTest(): void {
  waitingWorker = false;
  versionBanner = false;
  reloading = false;
  updateSW = null;
  stopWatchingDialogs?.();
  deps.buildVersion = BUILD_VERSION;
  deps.reload = () => window.location.reload();
  emit();
}

export function setVersionCheckForTest(overrides: { buildVersion?: string; reload?: () => void }): void {
  if (overrides.buildVersion !== undefined) deps.buildVersion = overrides.buildVersion;
  if (overrides.reload) deps.reload = overrides.reload;
}
