// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

/**
 * A docs file in the repository (for example a page under `website/src/content/docs/`) of exactly the running build, built from its
 * `source_url` (D20): `…/tree/<ref>` becomes `…/blob/<ref>/<path>`; a bare repository URL takes
 * the default branch. Null while `/api/v1/info` has not answered.
 */
export function docsUrl(sourceUrl: string | null | undefined, path: string): string | null {
  if (!sourceUrl) return null;
  const tree = /^(.+)\/tree\/([^/]+)$/.exec(sourceUrl);
  return tree ? `${tree[1]}/blob/${tree[2]}/${path}` : `${sourceUrl}/blob/main/${path}`;
}
