// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useLingui } from "@lingui/react/macro";

export type BadgeState = "ok" | "warn" | "bad" | "idle";

const SHAPE_COLOUR: Record<BadgeState, string> = {
  ok: "text-ok",
  warn: "text-warn",
  bad: "text-bad",
  idle: "text-ink-3",
};

/**
 * A state is always a shape plus a word (spec 5.2): colour alone never says it.
 * `warn` is a diamond because its orange sits close to the amber accent.
 */
export function StatusBadge({ state, label }: { state: BadgeState; label: string }) {
  const { t } = useLingui();
  const fallback: Record<BadgeState, string> = {
    ok: t`OK`,
    warn: t`Warning`,
    bad: t`Problem`,
    idle: t`Idle`,
  };
  const text = label.trim() === "" ? fallback[state] : label;
  const diamond = state === "warn";
  return (
    <span className="inline-flex items-center gap-2 text-small leading-5 text-ink">
      <svg
        viewBox="0 0 10 10"
        width="10"
        height="10"
        aria-hidden="true"
        focusable="false"
        data-shape={diamond ? "diamond" : "dot"}
        className={`shrink-0 fill-current ${SHAPE_COLOUR[state]}`}
      >
        {diamond ? <polygon points="5,0 10,5 5,10 0,5" /> : <circle cx="5" cy="5" r="5" />}
      </svg>
      <span>{text}</span>
    </span>
  );
}
