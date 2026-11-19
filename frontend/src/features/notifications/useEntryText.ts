// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { plural } from "@lingui/core/macro";
import { useLingui } from "@lingui/react/macro";
import { useStoredJobErrorText } from "../jobs/jobErrorText";
import { useFlagText } from "../printers/flags";
import { useKindLabel, type PrinterKind } from "../printers/model";
import { useReasonWord } from "../printers/reasons";
import { useRollWords } from "../printers/roll";
import type { Notification } from "./derive";

/**
 * The one sentence of an entry, in the active language. `derive.ts` keeps the words out (it only names the sentence and
 * its parts); this is where `textKey` and `values` become text. A part the data did not carry gets a plain word.
 */
function detailOf(json: string | undefined): Record<string, unknown> | null {
  if (!json) return null;
  try {
    const value: unknown = JSON.parse(json);
    return typeof value === "object" && value !== null && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

export function useEntryText(): (entry: Pick<Notification, "textKey" | "values">) => string {
  const { t } = useLingui();
  const kinds = useKindLabel();
  const reasonWord = useReasonWord();
  const flagText = useFlagText();
  const storedError = useStoredJobErrorText();
  const rollWords = useRollWords();

  return ({ textKey, values }) => {
    const title = values.title || t`Label`;
    const printer = values.printer || t`Unknown printer`;
    switch (textKey) {
      case "job.queued":
        return t`${title} is waiting on ${printer}`;
      case "job.printing":
        return t`${title} is printing on ${printer}`;
      case "job.done":
        return t`${title} printed`;
      case "job.cancelled":
        return t`${title} was cancelled`;
      case "job.retried":
        return t`${title} failed, printed on retry`;
      case "job.failed": {
        const error = (storedError(values.error, detailOf(values.errorDetail)) ?? "").trim();
        return error ? t`${title} failed: ${error}` : t`${title} failed`;
      }
      case "printer.flag": {
        // The flag in words, never the raw name (#376); a waiting job or a refused print says why it is a problem.
        const headline = flagText(values.flag ?? "").headline;
        const job = values.job ?? "";
        if (values.refused) return t`${printer}: ${headline} · a print was refused`;
        if (job) return t`${printer}: ${headline} · ${job} is waiting`;
        return t`${printer}: ${headline}`;
      }
      case "printer.unsupported_roll": {
        const roll = { kind: "die_cut" as const, widthMm: null, lengthMm: null };
        const inline = values.size ? `${values.size} ${rollWords(roll).inline}` : rollWords(roll).inline;
        return t`${printer}: Unsupported roll loaded: ${inline}`;
      }
      case "printer.different_device":
        return t`Different device at the address of ${printer}`;
      case "printer.material": {
        const parts: string[] = [];
        if (values.empty) {
          const names = values.empty;
          parts.push(t`${names} empty`);
        }
        if (values.low) {
          const names = values.low;
          parts.push(t`${names} low`);
        }
        const what = parts.join(" · ");
        return t`${printer}: ${what}`;
      }
      case "sheet.unconfirmed": {
        const cells = plural(Number(values.count) || 0, { one: "# unconfirmed cell", other: "# unconfirmed cells" });
        const code = values.code ?? "";
        return t`${cells} on sheet ${code}`;
      }
      case "sheet_type.updated": {
        const code = values.code ?? "";
        return t`${code} dimensions updated (verified)`;
      }
      case "sheet_type.verified": {
        const code = values.code ?? "";
        return t`${code} marked as verified`;
      }
      case "update.available": {
        const version = values.version ?? "";
        return version ? t`New version ${version} available` : t`New version available`;
      }
      default: {
        if (textKey.startsWith("printer.")) {
          const kind = kinds[textKey.slice("printer.".length) as PrinterKind];
          if (kind) {
            const more = [values.detail, ...(values.reasons ? values.reasons.split(",").map(reasonWord) : [])].filter(Boolean).join(" · ");
            return more ? t`${printer}: ${kind} (${more})` : t`${printer}: ${kind}`;
          }
        }
        return textKey;
      }
    }
  };
}
