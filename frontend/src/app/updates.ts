import { useSyncExternalStore } from "react";

/** What `registerSW` from vite-plugin-pwa looks like to us (so tests can stand in for it). */
export type RegisterSW = (options: { onNeedRefresh: () => void }) => (reloadPage?: boolean) => Promise<void>;

let needRefresh = false;
let updateSW: ((reloadPage?: boolean) => Promise<void>) | null = null;
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());

/**
 * Starts the service worker. A new version waits (it is not forced on open tabs, whose lazy
 * files would be gone) until the person chooses to reload; then `needRefresh` turns true.
 */
export function startUpdates(register: RegisterSW): void {
  updateSW = register({
    onNeedRefresh() {
      needRefresh = true;
      emit();
    },
  });
}

/** Activates the waiting version and reloads the page. */
export function applyUpdate(): void {
  void updateSW?.(true);
}

export function useNeedRefresh(): boolean {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => needRefresh,
  );
}

export function resetUpdatesForTest(): void {
  needRefresh = false;
  updateSW = null;
  emit();
}
