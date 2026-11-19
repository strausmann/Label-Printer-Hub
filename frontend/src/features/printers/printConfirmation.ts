// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { msg } from "@lingui/core/macro";
import type { Printer } from "./api";
import type { Translate } from "./printErrorText";

/**
 * How a tape printer confirms that a label printed (#393), as its last test print found it. A printer that was
 * never test-printed has no record yet; the hub then asks the printer each time it sends.
 */
export function printConfirmationText(confirmation: Printer["print_confirmation"], t: Translate): string {
  const channel = channelText(confirmation, t);
  // Run 26, hardening note 3: say why test prints no longer try IPP.
  if (confirmation?.channel !== "ipp" && confirmation?.ipp_incomplete) {
    if (confirmation.label_counter && confirmation.counter_read === false) {
      // R3-7: both apply, say both.
      return t(
        msg`Not confirmed — the label counter does not answer, and IPP is not tried: the printer did not finish a test print's IPP job`,
      );
    }
    return confirmation.channel === "none"
      ? t(msg`Not confirmed — IPP is not tried: the printer did not finish a test print's IPP job`)
      : t(msg`Label counter — IPP is not tried: the printer did not finish a test print's IPP job`);
  }
  return channel;
}

function channelText(confirmation: Printer["print_confirmation"], t: Translate): string {
  switch (confirmation?.channel) {
    case "ipp":
      return t(msg`Printer reports the job state (IPP)`);
    case "label_counter":
      return t(msg`Label counter`);
    case "none":
      // R26-1: the test print found a label counter, but the printer has stopped answering it.
      return confirmation?.label_counter && confirmation.counter_read === false
        ? t(msg`Not confirmed — the label counter does not answer; a test print checks again`)
        : t(msg`Not confirmed`);
    default:
      return t(msg`Not tested yet — a test print finds out`);
  }
}
