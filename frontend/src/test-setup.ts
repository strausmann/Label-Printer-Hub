// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";
import { resetPrintWatch } from "./features/jobs/printWatch";

// Vitest globals are off, so Testing Library cannot register its own cleanup.
// The print-status store is module state: a print started in one test must not show up in the next.
afterEach(() => {
  cleanup();
  resetPrintWatch();
});

// jsdom has no EventSource. Tests of the shell get one that never connects;
// tests of the stream itself (api/events.test.ts) stub their own.
class IdleEventSource {
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  addEventListener(): void {}
  close(): void {}
}
globalThis.EventSource ??= IdleEventSource as unknown as typeof EventSource;

// jsdom does not implement scrolling and logs "Not implemented" for every call.
// Pages scroll to the top on navigation; nothing here asserts on it.
window.scrollTo = () => {};
