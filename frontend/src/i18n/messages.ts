// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { msg } from "@lingui/core/macro";

/**
 * Shared message descriptors. Resolve them at render time with `i18n._(descriptor)`
 * (or `useLingui()._`) so a language switch takes effect without a reload.
 */
export const messages = {
  appName: msg`Labelyard`,
  tagline: msg`The self-hosted Label Printer Hub for all your labels`,
  loading: msg`Loading…`,
  retry: msg`Try again`,
  somethingWentWrong: msg`Something went wrong.`,
  sessionExpired: msg`Your session has expired. Sign in again.`,
  serverUnreachable: msg`The server cannot be reached.`,
};
