// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import type { ScanResolver } from "../scan/resolvers";

/*
 * Pure on purpose: this file must not import `scan/resolvers`. That module registers the
 * foundation resolvers at load time and imports this one to register it afterwards, so an import
 * the other way round would evaluate this file first and hit the registry before it exists.
 */

/** The server's `CodePath`: one upper-case letter, up to nine letters or digits, a dash, 4+ digits. */
const SHEET_CODE = /^[A-Z][A-Z0-9]{1,9}-[0-9]{4,}$/;
const MAX_CODE_LENGTH = 24;
/** The last path segment after `/sheet/`, also behind a sub-path or with a trailing slash. */
const SHEET_PATH = /(?:^|\/)sheet\/([^/]+)\/?$/;
const SHORT_FORM = /^sheet:(.+)$/i;

const asCode = (candidate: string): string | null =>
  candidate.length <= MAX_CODE_LENGTH && SHEET_CODE.test(candidate) ? candidate : null;

/**
 * The sheet code a scanned text names: a printed link `{any origin}/sheet/{CODE}` (the host is
 * ignored; only the path counts) or the short form `sheet:{CODE}`. Upper case only, like the
 * codes the hub issues. Anything else is null.
 */
export function parseSheetCode(raw: string): string | null {
  const text = raw.trim();
  const short = SHORT_FORM.exec(text);
  if (short) return asCode(short[1]!);
  let pathname: string;
  try {
    if (text.startsWith("/")) {
      pathname = new URL(text, "http://hub.invalid").pathname;
    } else {
      const url = new URL(text);
      if (url.protocol !== "http:" && url.protocol !== "https:") return null;
      pathname = url.pathname;
    }
  } catch {
    return null;
  }
  const match = SHEET_PATH.exec(pathname);
  if (!match) return null;
  try {
    return asCode(decodeURIComponent(match[1]!));
  } catch {
    return null;
  }
}

export const sheetResolver: ScanResolver = {
  id: "sheet",
  match: (hit) => parseSheetCode(hit.text) !== null,
  resolve: (hit) => `/sheet/${parseSheetCode(hit.text)!}`,
};
