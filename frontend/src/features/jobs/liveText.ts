// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useLingui } from "@lingui/react/macro";
import type { BadgeState } from "../../shell/StatusBadge";
import type { JobLive, JobPhase } from "./printWatch";

/**
 * The state of a live print in words, with the page job's place at the printer where the events say so.
 * One source for the notification stack and for the status line on the calibration page, so the two
 * never word the same job differently.
 */
export function useStateWords(): (phase: JobPhase, live: JobLive | undefined) => string {
  const { t } = useLingui();
  return (phase, live) => {
    switch (phase) {
      // No "N jobs ahead": no event or endpoint tells this job's place in the queue, and a wrong number is worse than none.
      case "queued":
        return t`Queued`;
      case "paused":
        return t`Paused`;
      case "printing":
        if (live?.atPrinter === "waiting") return t`Waiting at the printer`;
        if (live?.atPrinter === "stopped") return t`Stopped at the printer`;
        return t`Printing`;
      case "done":
        return t`Done`;
      case "failed":
        return t`Failed`;
      case "cancelled":
        return t`Cancelled`;
    }
  };
}

/** The badge colour of a live print: calm states idle, a job stopped at the printer needs someone. */
export function badgeOf(phase: JobPhase, live: JobLive | undefined): BadgeState {
  switch (phase) {
    case "printing":
      return live?.atPrinter === "stopped" ? "warn" : "ok";
    case "done":
      return "ok";
    case "failed":
      return "bad";
    default:
      return "idle";
  }
}
