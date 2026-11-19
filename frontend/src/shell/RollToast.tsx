// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useLingui } from "@lingui/react/macro";
import { Link } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import type { Notification } from "../features/notifications/derive";
import { SeverityShape } from "../features/notifications/NotificationCentre";
import { useEntryText } from "../features/notifications/useEntryText";
import { useNotifications } from "../features/notifications/useNotifications";

const ROLL_TEXT_KEY = "printer.unsupported_roll";

const isRoll = (e: Notification) => e.textKey === ROLL_TEXT_KEY;

/** Printer id → the roll entry id the printer showed at the first full read; a printer without a roll has none. */
export function rollBaseline(entries: readonly Notification[]): Record<string, string> {
  const baseline: Record<string, string> = {};
  for (const e of entries) if (isRoll(e)) baseline[e.target.params.printerId ?? ""] = e.id;
  return baseline;
}

/**
 * The roll entries that are a change: a printer whose roll key differs from the baseline taken at the first full status read
 * after the page opened (also from "no such roll"). Reloading, or opening the app in a new browser, finds the roll already
 * there and so toasts nothing; the card and the bell say it. Pure.
 */
export function newRollEntries(visible: readonly Notification[], baseline: Readonly<Record<string, string>>, toasted: ReadonlySet<string>): Notification[] {
  return visible.filter((e) => isRoll(e) && !toasted.has(e.id) && baseline[e.target.params.printerId ?? ""] !== e.id);
}

/** One toast per roll change that leaves a roll in the printer the hub cannot print on yet (#391). It stays until closed. */
export function RollToast() {
  const { t } = useLingui();
  const feed = useNotifications();
  const text = useEntryText();
  // The roll each printer held at the first full read; nothing toasts before it exists.
  const [baseline, setBaseline] = useState<Record<string, string> | null>(null);
  if (baseline === null && feed.printersRead) setBaseline(rollBaseline(feed.entries));
  const [closed, setClosed] = useState<ReadonlySet<string>>(new Set());
  const fresh = useMemo(() => (baseline ? newRollEntries(feed.visible, baseline, closed) : []), [feed.visible, baseline, closed]);
  // Once shown, a toast stays until it is closed.
  const [shown, setShown] = useState<Notification[]>([]);
  const pending = fresh.filter((e) => !shown.some((s) => s.id === e.id));
  if (pending.length > 0) setShown((s) => [...s, ...pending]);
  const open = shown.filter((e) => !closed.has(e.id) && feed.entries.some((x) => x.id === e.id));
  if (open.length === 0) return null;
  return (
    <div className="fixed inset-x-4 top-4 z-30 flex flex-col gap-2 lg:inset-x-auto lg:right-6 lg:w-[28rem]">
      {open.map((entry) => (
        <section key={entry.id} aria-label={t`Roll not supported`} className="update-toast flex flex-wrap items-center gap-x-4 gap-y-2 rounded-r3 px-4 py-3 shadow-lg">
          <div role="status" className="flex min-w-0 flex-1 items-start gap-2.5">
            <span className="mt-1.5">
              <SeverityShape severity={entry.severity} />
            </span>
            <span className="font-bold [overflow-wrap:anywhere]">{text(entry)}</span>
          </div>
          <div className="ml-auto flex shrink-0 items-center gap-1">
            <Link to="/printers/$printerId" params={{ printerId: entry.target.params.printerId ?? "" }} className="inline-flex h-11 items-center rounded-r2 px-3 text-small font-bold text-(--toast-ink) underline underline-offset-2">
              {t`Open printer`}
            </Link>
            <button type="button" onClick={() => setClosed((c) => new Set([...c, entry.id]))} className="press inline-flex h-11 items-center rounded-r2 px-3 text-small text-(--toast-ink-2) hover:text-(--toast-ink)">
              {t`Close`}
            </button>
          </div>
        </section>
      ))}
    </div>
  );
}
