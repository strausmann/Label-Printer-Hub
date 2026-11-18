// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import type { MessageDescriptor } from "@lingui/core";
import { msg } from "@lingui/core/macro";
import { useLingui } from "@lingui/react";
import { ApiError } from "../../api/client";
import { flagText } from "./flags";

export type Translate = (d: MessageDescriptor) => string;

/** `printer-cover-open`, `printer_cover_open` and `…/printer-cover-open` are one code. */
export function normalise(code: string): string {
  return (code.split("/").pop() ?? code).replaceAll("-", "_");
}

const mm = (value: unknown): number | null => {
  const n = typeof value === "number" ? value : Number.NaN;
  return Number.isFinite(n) ? n : null;
};

/**
 * The app's own words for a known printer or render error (#378), whatever body shape the route answered with
 * (snake codes of the envelope, kebab types of a problem). Null for a code it does not know: the caller then shows
 * the server's text or its own fallback.
 */
export function printErrorText(code: string | null | undefined, detail: Record<string, unknown> | null, t: Translate): string | null {
  if (!code) return null;
  switch (normalise(code)) {
    case "unsupported_tape": {
      if (Array.isArray(detail?.content_types)) {
        // #346: a cart with other labels on a DK width only the spool label has.
        const tapeMm = Number(detail?.tape_mm);
        return t(msg`Only the spool label prints on ${tapeMm} mm tape. Remove the other labels from the cart or load 62 mm tape.`);
      }
      const tapeMm = mm(detail?.tape_mm);
      return tapeMm === null
        ? t(msg`This tape width cannot print this label. Load another tape.`)
        : t(msg`This label cannot print on ${tapeMm} mm tape. Load another tape.`);
    }
    case "printer_cover_open":
      return t(msg`The printer cover is open. Close it and try again.`);
    case "no_tape_loaded":
      return t(msg`No tape is loaded. Put in a tape and try again.`);
    case "tape_empty":
      return t(msg`The tape is empty. Put in a new tape and try again.`);
    case "tape_mismatch": {
      const loaded = mm(detail?.loaded_mm);
      const expected = mm(detail?.expected_mm);
      return loaded !== null && expected !== null
        ? t(msg`The loaded tape (${loaded} mm) does not match this label (${expected} mm).`)
        : t(msg`The loaded tape does not match this label.`);
    }
    case "printer_error": {
      // #389: the blocking bits the printer reports, in the words of #376.
      const flags = Array.isArray(detail?.flags) ? detail.flags.filter((f): f is string => typeof f === "string") : [];
      if (flags.length === 0) return t(msg`The printer reports an error. Fix it on the printer and try again.`);
      const words = flags.map((f) => flagText(f, t).headline).join(" · ");
      return t(msg`The printer reports: ${words}. Fix it on the printer and try again.`);
    }
    case "labels_not_confirmed": {
      // #393: the printer confirmed fewer labels than were sent.
      const printed = Number(detail?.printed);
      const expected = Number(detail?.expected);
      return Number.isFinite(printed) && Number.isFinite(expected)
        ? t(msg`The printer confirmed ${printed} of ${expected} labels. Reprint the rest.`)
        : t(msg`The printer did not confirm every label. Reprint the rest.`);
    }
    case "media_type_mismatch":
      return t(msg`The loaded roll is die-cut labels. The hub prints on continuous tape only; put in a continuous roll.`);
    case "content_type_data_mismatch":
      return t(msg`The label is missing data this layout needs.`);
    case "printer_disabled":
      // The server's text names the printer's id: the app says it in its own words.
      return t(msg`The printer is switched off in the hub. Switch it on in the printer settings.`);
    case "printer_offline":
    case "snmp_query_failed":
      return t(msg`The printer is not reachable. Check that it is switched on and connected, then try again.`);
    case "qr_payload_too_long": {
      const length = Number(detail?.length);
      const max = Number(detail?.max_bytes);
      return Number.isFinite(length) && Number.isFinite(max)
        ? t(msg`The link in the QR code is ${length} bytes long, but this layout holds at most ${max} bytes. Pick another arrangement or a shorter link.`)
        : t(msg`The link in the QR code is too long for this layout.`);
    }
    case "conflicting_orientation":
      return t(msg`These labels ask for different directions (along and across). Print them in separate runs.`);
    default:
      return null;
  }
}

/** `printErrorText` bound to the active language: null for a code it does not know. */
export function usePrintErrorWords(): (code: string, detail: Record<string, unknown> | null) => string | null {
  const { i18n } = useLingui();
  return (code, detail) => printErrorText(code, detail, (d) => i18n._(d));
}

/**
 * The words for a refused print: the app's own for a known code, then the server's wording when it gave one, else a
 * plain fallback.
 */
export function usePrintErrorText(): (error: unknown) => string {
  const { i18n } = useLingui();
  const t: Translate = (d) => i18n._(d);
  return (error) => {
    if (error instanceof ApiError) {
      if (error.status === 0) return t(msg`The server cannot be reached.`);
      const known = printErrorText(error.code, error.errorDetail, t);
      if (known !== null) return known;
      if (error.detail && !/^HTTP \d+$/.test(error.detail)) return error.detail;
    }
    return t(msg`The labels could not be sent.`);
  };
}
