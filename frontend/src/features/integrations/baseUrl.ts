// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import type { LookupApp } from "../lookup/cart";

/** The deep links the plugins build (each plugin under `backend/app/integrations`), read back to the app's root. */
const DEEP_LINK: Record<LookupApp, RegExp> = {
  snipeit: /^(.*)\/(?:hardware|locations)\/[^/]+$/,
  grocy: /^(.*)\/product\/[^/]+$/,
  spoolman: /^(.*)\/spool\/show\/[^/]+$/,
};

/** `https://host/hardware/7` -> `https://host`; null when the link is not one of the known shapes. */
export function baseUrlOf(app: LookupApp, deepLink: string): string | null {
  try {
    const url = new URL(deepLink);
    const match = DEEP_LINK[app].exec(url.pathname);
    return match ? `${url.origin}${match[1]}` : null;
  } catch {
    return null;
  }
}
