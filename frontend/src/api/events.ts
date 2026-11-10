import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { pageJobStateFrom, pageJobStateKey } from "../features/jobs/pageJobState";
import { previewNamesCode, SHEET_PREVIEW_KEY, sheetKey, sheetsListKey, typesListKey } from "../features/sheets/keys";
import { isSessionUnknown, notifyUnauthorized, onSessionConfirmed } from "./client";

const EVENTS_URL = "/api/v1/events";
const BACKOFF_START_MS = 1_000;
const BACKOFF_MAX_MS = 30_000;

/** The frame types the backend sends (`event: <type>`); keep-alive comments never reach us. */
const EVENT_TYPES = [
  "job.state_changed",
  "printer.status",
  "printer.tape_changed",
  "printer.roll_changed",
  // Carries only `{mismatch, since}`: the status and the printer are read again for the rest.
  "printer.identity_mismatch",
  "hub.printers_changed",
  "auth.expired",
  // The `sheets` channel (no printer restriction); the client filters by event type, not channel.
  "sheet.updated",
] as const;
type EventType = (typeof EVENT_TYPES)[number];

interface Frame {
  printerId: string | null;
  data: Record<string, unknown>;
}

const isRecord = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);

function parseFrame(frame: MessageEvent): Frame {
  try {
    const payload: unknown = JSON.parse(String(frame.data));
    if (isRecord(payload)) {
      const id = payload.printer_id;
      return { printerId: typeof id === "string" && id !== "" ? id : null, data: isRecord(payload.data) ? payload.data : {} };
    }
  } catch {
    // Unreadable body: the event type alone still says which lists are stale.
  }
  return { printerId: null, data: {} };
}

/** Which cached queries an event makes stale. Task 11 relies on these keys. */
function invalidate(client: QueryClient, type: EventType, { printerId, data }: Frame): void {
  const run = (queryKey: readonly unknown[]) => void client.invalidateQueries({ queryKey });
  switch (type) {
    case "job.state_changed": {
      // A page job's place at the printer changes with from_state == to_state, so a refetch of the
      // job returns nothing new: keep the event's own data for the job views.
      const pageJob = pageJobStateFrom(data);
      if (pageJob) client.setQueryData(pageJobStateKey(pageJob.jobId), pageJob.state);
      run(["jobs"]);
      if (printerId) run(["printers", printerId, "queue"]);
      break;
    }
    case "sheet.updated": {
      run(sheetsListKey);
      // Sheet counts of the types (sheets_in_use, per version) move with every sheet; the event names no type.
      run(typesListKey.slice(0, 1));
      const code = typeof data.code === "string" ? data.code : null;
      if (!code) break;
      run(sheetKey(code));
      // Only previews that name the code: a worst-case preview takes seconds to render.
      void client.invalidateQueries({
        queryKey: [SHEET_PREVIEW_KEY],
        predicate: (query) => previewNamesCode(query.queryKey, code),
      });
      break;
    }
    case "printer.status":
      run(["printers"]);
      if (printerId) run(["printers", printerId]);
      break;
    case "printer.tape_changed":
      if (printerId) run(["printers", printerId]);
      break;
    case "printer.identity_mismatch":
      // The cards read the status flag, the detail page the printer (admin: both identities) and its status.
      run(["printers"]);
      if (printerId) run(["printers", printerId]);
      break;
    case "printer.roll_changed":
      // The roll (and with it the prompt and the colour) is part of the status; both queries are refetched.
      if (printerId) {
        run(["printers", printerId, "status"]);
        run(["printers", printerId, "roll"]);
      }
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
    let openedBefore = false;

    const close = () => {
      if (source) {
        source.onopen = null;
        source.onerror = null;
        source.close();
        source = null;
      }
    };

    // While the session is unverified no stream is opened: wait for a definitive answer.
    const waitForConfirmation = () => {
      stopWaiting?.();
      stopWaiting = onSessionConfirmed(() => {
        stopWaiting?.();
        stopWaiting = null;
        resume();
      });
    };

    const resume = () => {
      if (disposed) return;
      stopped = false;
      timer = setTimeout(open, delay);
      delay = Math.min(delay * 2, BACKOFF_MAX_MS);
    };

    const open = () => {
      close();
      if (isSessionUnknown()) {
        setConnected(false);
        setConnecting(false);
        waitForConfirmation();
        return;
      }
      const es = new EventSource(EVENTS_URL, { withCredentials: true });
      source = es;
      es.onopen = () => {
        // The snapshot of a fresh stream has no sheet frames, so a `sheet.updated` sent while the
        // stream was down never arrives: whatever shows sheets is fetched again.
        if (openedBefore) {
          void queryClient.invalidateQueries({ queryKey: sheetsListKey.slice(0, 1) });
          void queryClient.invalidateQueries({ queryKey: typesListKey.slice(0, 1) });
          void queryClient.invalidateQueries({ queryKey: [SHEET_PREVIEW_KEY] });
        }
        openedBefore = true;
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
            void notifyUnauthorized().then((verdict) => {
              if (disposed || verdict === "signed_out") return;
              if (verdict === "valid") return resume();
              // No definitive answer: stay down until a later check confirms the session.
              waitForConfirmation();
            });
            return;
          }
          invalidate(queryClient, type, parseFrame(frame as MessageEvent));
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
      // The stream may stay down; the visible data still refreshes (not while the session is unverified).
      if (!isSessionUnknown()) void queryClient.invalidateQueries();
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
