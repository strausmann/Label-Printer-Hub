// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

declare module "*.po" {
  import type { Messages } from "@lingui/core";
  export const messages: Messages;
}
