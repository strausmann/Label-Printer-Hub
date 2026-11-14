// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useLingui } from "@lingui/react/macro";
import { useEffect, useState } from "react";
import { StatusBadge } from "./StatusBadge";

const PAUSED_AFTER_MS = 5_000;

/** Non-blocking note once the live stream has been down for more than 5 s. */
export function LiveStatus({
  connected,
  connecting,
  onReconnect,
}: {
  connected: boolean;
  connecting: boolean;
  onReconnect: () => void;
}) {
  const { t } = useLingui();
  // "Down for 5 s": set by the timer only; being connected overrides it, so no reset is needed.
  const [downLong, setDownLong] = useState(false);

  useEffect(() => {
    if (connected) return;
    const timer = setTimeout(() => setDownLong(true), PAUSED_AFTER_MS);
    return () => {
      clearTimeout(timer);
      setDownLong(false);
    };
  }, [connected]);

  if (connected || !downLong) return null;
  return (
    <div className="mb-4 flex flex-wrap items-center gap-4">
      <div role="status">
        <StatusBadge state="warn" label={t`Live updates paused`} />
      </div>
      <button
        type="button"
        onClick={onReconnect}
        disabled={connecting}
        aria-busy={connecting}
        className="inline-flex h-11 items-center rounded-r2 border border-line-strong bg-surface px-4 text-small font-bold text-ink focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-link disabled:opacity-60"
      >
        {connecting ? t`Reconnecting…` : t`Reconnect`}
      </button>
    </div>
  );
}
