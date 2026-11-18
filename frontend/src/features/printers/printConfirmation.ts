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
  switch (confirmation?.channel) {
    case "ipp":
      return t(msg`Printer reports the job state (IPP)`);
    case "label_counter":
      return t(msg`Label counter`);
    case "none":
      return t(msg`Not confirmed`);
    default:
      return t(msg`Not tested yet — a test print finds out`);
  }
}
