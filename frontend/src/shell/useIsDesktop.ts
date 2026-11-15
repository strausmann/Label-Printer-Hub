// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useSyncExternalStore } from "react";

/** The width at which the sidebar and the inline search take over from the tab bar and the magnifier (Tailwind's `lg`). */
export const DESKTOP_QUERY = "(min-width: 1024px)";

function subscribe(listener: () => void): () => void {
  const query = window.matchMedia?.(DESKTOP_QUERY);
  query?.addEventListener("change", listener);
  return () => query?.removeEventListener("change", listener);
}

// A browser without matchMedia (and jsdom) counts as a desktop: the inline field is the plain, always-present control.
const read = () => window.matchMedia?.(DESKTOP_QUERY).matches ?? true;

/** Is the screen 1024 px wide or more? Follows a change of the window (rotation, resize). */
export function useIsDesktop(): boolean {
  return useSyncExternalStore(subscribe, read, () => true);
}
