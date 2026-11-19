// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

/** The public documentation site; the app links to it for what does not fit on a screen. */
export const DOCS_SITE = "https://labelyard.app";

/** A page of the docs site in the language of the UI: German pages live under `/de/`, English ones at the root. */
export function docsUrl(path: string, locale: string): string {
  const prefix = locale === "de" ? "/de" : "";
  return `${DOCS_SITE}${prefix}/${path.replace(/^\/+|\/+$/g, "")}/`;
}
