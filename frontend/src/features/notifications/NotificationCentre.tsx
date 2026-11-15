// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useLingui } from "@lingui/react/macro";
import { Link } from "@tanstack/react-router";
import { useEffect, useState, useSyncExternalStore, type ReactNode } from "react";
import { Button, Dialog, DialogTrigger, Heading, Modal, ModalOverlay, Popover } from "react-aria-components";
import { BellIcon } from "../../shell/icons";
import { formatAge } from "../printers/age";
import type { Notification, Severity } from "./derive";
import { useEntryText } from "./useEntryText";
import { useNotifications, type Feed } from "./useNotifications";

const FOCUS =
  "data-[focus-visible]:outline-3 data-[focus-visible]:outline-offset-2 data-[focus-visible]:outline-link focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-link";
const ICON_BUTTON =
  "press relative flex h-11 min-w-11 items-center justify-center gap-1 rounded-r2 px-2 text-ink-2 transition-colors duration-150 data-[hovered]:bg-sunken data-[hovered]:text-ink data-[pressed]:bg-sunken " + FOCUS;
const ACTION =
  "press inline-flex h-11 items-center justify-center rounded-r2 border border-line-strong bg-surface px-4 text-small font-bold text-ink transition-colors duration-150 data-[hovered]:bg-sunken data-[disabled]:opacity-60 " + FOCUS;

/** Below this width the panel is a full-height sheet (Tailwind's `sm`). */
const PHONE_QUERY = "(max-width: 639.98px)";

function usePhone(): boolean {
  return useSyncExternalStore(
    (listener) => {
      const list = window.matchMedia?.(PHONE_QUERY);
      list?.addEventListener("change", listener);
      return () => list?.removeEventListener("change", listener);
    },
    () => window.matchMedia?.(PHONE_QUERY).matches ?? false,
    () => false,
  );
}

const SHAPE_COLOUR: Record<Severity, string> = { error: "text-bad", warning: "text-warn", success: "text-ok", info: "text-ok" };

/** A severity is a shape plus a word, never colour alone (spec 5.2): the warning is the diamond, the rest are dots. */
export function SeverityShape({ severity, size = 10 }: { severity: Severity; size?: number }) {
  const diamond = severity === "warning";
  return (
    <svg
      viewBox="0 0 10 10"
      width={size}
      height={size}
      aria-hidden="true"
      focusable="false"
      data-shape={diamond ? "diamond" : "dot"}
      data-severity={severity}
      className={`shrink-0 fill-current ${SHAPE_COLOUR[severity]}`}
    >
      {diamond ? <polygon points="5,0 10,5 5,10 0,5" /> : <circle cx="5" cy="5" r="5" />}
    </svg>
  );
}

function useSeverityLabel(): Record<Severity, string> {
  const { t } = useLingui();
  return { error: t`Error`, warning: t`Warning`, success: t`Success`, info: t`Information` };
}

/** "Notifications, 3 unread, the most severe is an error". */
function useBellName(badge: Feed["badge"]): string {
  const { t } = useLingui();
  const { severity, unread } = badge;
  if (severity === null) return t`Notifications, nothing unread`;
  switch (severity) {
    case "error":
      return t`Notifications, ${unread} unread, the most severe is an error`;
    case "warning":
      return t`Notifications, ${unread} unread, the most severe is a warning`;
    case "success":
      return t`Notifications, ${unread} unread, the most severe is a success`;
    case "info":
      return t`Notifications, ${unread} unread, the most severe is information`;
  }
}

/** A link to the entry's page; one branch per route so the router keeps its types. */
function EntryLink({ entry, className, onClick, title, children }: { entry: Notification; className: string; onClick: () => void; title?: string; children: ReactNode }) {
  const { to, params } = entry.target;
  const common = { className, onClick, title };
  switch (to) {
    case "/jobs/$jobId":
      return <Link to="/jobs/$jobId" params={{ jobId: params.jobId ?? "" }} {...common}>{children}</Link>;
    case "/printers/$printerId":
      return <Link to="/printers/$printerId" params={{ printerId: params.printerId ?? "" }} {...common}>{children}</Link>;
    case "/sheets/$code":
      return <Link to="/sheets/$code" params={{ code: params.code ?? "" }} {...common}>{children}</Link>;
  }
}

/** The clock of the open panel: relative times are measured against it, and it moves once a minute. */
function useClock(): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 60_000);
    return () => clearInterval(timer);
  }, []);
  return now;
}

/** "now" under a minute: the panel's clock moves once a minute, so seconds would be stale on screen (and differ per render). */
function ageLabel(seconds: number, locale: string): string {
  if (seconds < 60) return new Intl.RelativeTimeFormat(locale, { numeric: "auto" }).format(0, "second");
  return formatAge(seconds, locale);
}

function absoluteTime(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleString([], { dateStyle: "medium", timeStyle: "medium" });
}

function Entry({ entry, unread, now, onNavigate }: { entry: Notification; unread: boolean; now: number; onNavigate: () => void }) {
  const { t, i18n } = useLingui();
  const text = useEntryText();
  const severities = useSeverityLabel();
  const sentence = text(entry);
  const at = Date.parse(entry.at);
  const bold = unread ? "font-bold" : "";
  const source = entry.kind === "job" ? entry.values.printer || "" : entry.kind === "printer" ? t`Printer` : t`Sheet`;
  return (
    <li className="border-b border-line last:border-b-0" data-unread={unread || undefined}>
      <EntryLink
        entry={entry}
        onClick={onNavigate}
        className={`flex min-h-11 flex-col gap-1 px-4 py-3 text-ink data-[focus-visible]:outline-offset-[-3px] hover:bg-sunken ${FOCUS} focus-visible:outline-offset-[-3px]`}
      >
        <span className="flex items-center gap-2 text-small">
          <SeverityShape severity={entry.severity} />
          <span className={bold}>{severities[entry.severity]}</span>
          {unread && <span className="rounded-r2 bg-accent-soft px-1.5 font-bold text-ink">{t`New`}</span>}
          <time className="ml-auto shrink-0 text-ink-3" dateTime={entry.at} title={absoluteTime(entry.at)}>
            {Number.isNaN(at) ? "" : ageLabel(Math.max(0, (now - at) / 1000), i18n.locale)}
          </time>
        </span>
        <span title={sentence} className={`line-clamp-2 text-ink [overflow-wrap:anywhere] sm:line-clamp-1 ${bold}`}>
          {sentence}
        </span>
        {source && <span className="truncate text-small text-ink-3">{source}</span>}
      </EntryLink>
    </li>
  );
}

function PanelBody({ feed, livePaused, phone }: { feed: Feed; livePaused: boolean; phone: boolean }) {
  const { t } = useLingui();
  const now = useClock();
  const read = new Set(feed.state.read);

  return (
    <Dialog className="flex max-h-[inherit] min-h-0 flex-1 flex-col outline-none">
      {({ close }) => (
        <>
          <div className={`flex flex-col gap-2 border-b border-line p-4 ${phone ? "pt-[max(1rem,env(safe-area-inset-top))]" : ""}`}>
            <div className="flex items-center gap-2">
              <Heading slot="title" className="min-w-0 flex-1 text-section font-bold">
                {t`Notifications`}
              </Heading>
              {phone && (
                <Button
                  slot="close"
                  aria-label={t`Close`}
                  className={`press -my-2.5 -mr-2.5 flex size-11 shrink-0 items-center justify-center rounded-r2 text-ink-2 data-[hovered]:bg-sunken data-[hovered]:text-ink ${FOCUS}`}
                >
                  <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" className="fill-none stroke-current stroke-2 [stroke-linecap:round]">
                    <path d="M3.5 3.5 12.5 12.5M12.5 3.5 3.5 12.5" />
                  </svg>
                </Button>
              )}
            </div>
            <div className="flex flex-wrap gap-2">
              {/* The first action takes focus when the panel opens (spec 9): the person came to act on the list. */}
              {/* eslint-disable-next-line jsx-a11y/no-autofocus */}
              <Button autoFocus onPress={feed.markAllRead} className={ACTION}>
                {t`Mark all as read`}
              </Button>
              <Button onPress={feed.clearAll} isDisabled={feed.entries.length === 0} className={ACTION}>
                {t`Clear all`}
              </Button>
            </div>
          </div>

          <div className={`min-h-0 flex-1 overflow-y-auto overscroll-contain ${phone ? "pb-[env(safe-area-inset-bottom)]" : ""}`}>
            {livePaused && (
              <p role="status" className="flex items-center gap-2 border-b border-line bg-sunken px-4 py-3 text-small">
                <SeverityShape severity="warning" />
                <span>{t`Live updates paused; the list may be out of date.`}</span>
              </p>
            )}
            {feed.status === "loading" ? (
              <p role="status" className="px-4 py-6 text-ink-2">{t`Loading notifications…`}</p>
            ) : feed.status === "error" ? (
              <div role="alert" className="flex flex-col items-start gap-3 px-4 py-6">
                <p>{t`Notifications could not be loaded.`}</p>
                <Button onPress={feed.retry} className={ACTION}>
                  {t`Retry`}
                </Button>
              </div>
            ) : feed.visible.length === 0 ? (
              <p className="px-4 py-6 text-ink-2">{t`Nothing new.`}</p>
            ) : (
              <ul>
                {feed.visible.map((entry) => (
                  <Entry key={entry.id} entry={entry} unread={!read.has(entry.id)} now={now} onNavigate={close} />
                ))}
              </ul>
            )}
          </div>
        </>
      )}
    </Dialog>
  );
}

/**
 * The bell in the top bar (spec 9): the highest unread severity as a shape, the unread count, and the panel of
 * entries. A popover under the button on a desktop, a full-height sheet below 640 px that follows the visible area
 * (so the on-screen keyboard cannot push it out of sight).
 */
export function NotificationCentre({ livePaused = false }: { livePaused?: boolean }) {
  const feed = useNotifications();
  const phone = usePhone();
  const name = useBellName(feed.badge);
  const { severity, unread } = feed.badge;
  const count = unread > 99 ? "99+" : String(unread);

  return (
    <DialogTrigger>
      <Button aria-label={name} className={ICON_BUTTON}>
        <BellIcon />
        {severity !== null && (
          <span aria-hidden="true" className="flex items-center gap-1 text-small font-bold text-ink">
            <SeverityShape severity={severity} size={9} />
            {count}
          </span>
        )}
      </Button>
      {phone ? (
        <ModalOverlay
          isDismissable
          className="fixed inset-x-0 top-(--vv-top) z-50 h-(--vvh) bg-ink/40 data-[entering]:animate-[fadein_150ms_ease-out] motion-reduce:data-[entering]:animate-none"
        >
          <Modal className="flex h-full w-full flex-col overflow-hidden bg-surface data-[entering]:animate-[sheetin_150ms_cubic-bezier(0.23,1,0.32,1)] motion-reduce:data-[entering]:animate-none">
            <PanelBody feed={feed} livePaused={livePaused} phone />
          </Modal>
        </ModalOverlay>
      ) : (
        <Popover
          placement="bottom end"
          offset={8}
          shouldFlip={false}
          className="flex w-96 max-w-[calc(100vw-1rem)] max-h-[min(70vh,calc(var(--vvh)-5rem))] flex-col overflow-hidden rounded-r3 border border-line-strong bg-surface shadow-lg data-[entering]:animate-[liftin_150ms_cubic-bezier(0.23,1,0.32,1)] motion-reduce:data-[entering]:animate-none"
        >
          <PanelBody feed={feed} livePaused={livePaused} phone={false} />
        </Popover>
      )}
    </DialogTrigger>
  );
}

