import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { notifyUnauthorized, onSessionConfirmed } from "./client";

const EVENTS_URL = "/api/v1/events";
const BACKOFF_START_MS = 1_000;
const BACKOFF_MAX_MS = 30_000;

/** The frame types the backend sends (`event: <type>`); keep-alive comments never reach us. */
const EVENT_TYPES = [
  "job.state_changed",
  "printer.status",
  "printer.tape_changed",
  "hub.printers_changed",
  "auth.expired",
] as const;
type EventType = (typeof EVENT_TYPES)[number];

function printerIdOf(frame: MessageEvent): string | null {
  try {
    const payload: unknown = JSON.parse(String(frame.data));
    if (typeof payload === "object" && payload !== null && "printer_id" in payload) {
      const id = (payload as { printer_id: unknown }).printer_id;
      return typeof id === "string" && id !== "" ? id : null;
    }
  } catch {
    // Unreadable body: the event type alone still says which lists are stale.
  }
  return null;
}

/** Which cached queries an event makes stale. Task 11 relies on these keys. */
function invalidate(client: QueryClient, type: EventType, printerId: string | null): void {
  const run = (queryKey: readonly unknown[]) => void client.invalidateQueries({ queryKey });
  switch (type) {
    case "job.state_changed":
      run(["jobs"]);
      if (printerId) run(["printers", printerId, "queue"]);
      break;
    case "printer.status":
      run(["printers"]);
      if (printerId) run(["printers", printerId]);
      break;
    case "printer.tape_changed":
      if (printerId) run(["printers", printerId]);
      break;
    case "hub.printers_changed":
      run(["printers"]);
      break;
    case "auth.expired":
      break;
  }
}

/**
 * One `EventSource` per tab (mounted once in the shell). The server closes idle streams,
 * so a dropped stream is normal: reconnect with a doubling delay from 1 s up to 30 s.
 */
export function useHubEvents(): { connected: boolean; connecting: boolean; reconnect: () => void } {
  const queryClient = useQueryClient();
  const [connected, setConnected] = useState(false);
  // True from a manual reconnect until that attempt either opens or fails.
  const [connecting, setConnecting] = useState(false);
  const reconnectRef = useRef<() => void>(() => {});
  const reconnect = useCallback(() => reconnectRef.current(), []);

  useEffect(() => {
    let source: EventSource | null = null;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let delay = BACKOFF_START_MS;
    let stopped = false;
    let disposed = false;
    let stopWaiting: (() => void) | null = null;

    const close = () => {
      if (source) {
        source.onopen = null;
        source.onerror = null;
        source.close();
        source = null;
      }
    };

    const open = () => {
      close();
      const es = new EventSource(EVENTS_URL, { withCredentials: true });
      source = es;
      es.onopen = () => {
        delay = BACKOFF_START_MS;
        setConnected(true);
        setConnecting(false);
      };
      es.onerror = () => {
        // EventSource would retry on its own, but with a fixed delay and no cap on a dead session.
        close();
        setConnected(false);
        setConnecting(false);
        if (stopped) return;
        timer = setTimeout(open, delay);
        delay = Math.min(delay * 2, BACKOFF_MAX_MS);
      };
      for (const type of EVENT_TYPES) {
        es.addEventListener(type, (frame) => {
          if (type === "auth.expired") {
            // The stream ended; the session may not have (SSO renews, a key's printers changed).
            close();
            setConnected(false);
            if (timer) clearTimeout(timer);
            timer = null;
            stopped = true;
            const resume = () => {
              if (disposed) return;
              stopped = false;
              timer = setTimeout(open, delay);
              delay = Math.min(delay * 2, BACKOFF_MAX_MS);
            };
            void notifyUnauthorized().then((verdict) => {
              if (disposed || verdict === "signed_out") return;
              if (verdict === "valid") return resume();
              // No definitive answer: stay down until a later check confirms the session.
              stopWaiting?.();
              stopWaiting = onSessionConfirmed(() => {
                stopWaiting?.();
                stopWaiting = null;
                resume();
              });
            });
            return;
          }
          invalidate(queryClient, type, printerIdOf(frame as MessageEvent));
          // The printer set changed: a fresh stream starts from the new set at once.
          if (type === "hub.printers_changed") open();
        });
      }
    };

    reconnectRef.current = () => {
      if (stopped) return;
      if (timer) clearTimeout(timer);
      timer = null;
      delay = BACKOFF_START_MS;
      setConnecting(true);
      open();
      // The stream may stay down; the visible data still refreshes.
      void queryClient.invalidateQueries();
    };

    open();
    return () => {
      disposed = true;
      stopped = true;
      stopWaiting?.();
      if (timer) clearTimeout(timer);
      close();
    };
  }, [queryClient]);

  return { connected, connecting, reconnect };
}
