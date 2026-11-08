import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Vitest globals are off, so Testing Library cannot register its own cleanup.
afterEach(() => cleanup());

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
