import { msg } from "@lingui/core/macro";
import type { MessageDescriptor } from "@lingui/core";
import { useLingui } from "@lingui/react";

/** What `i18n._` / `useLingui()._` offers: turns a message descriptor into the active language. */
export type Translate = (descriptor: MessageDescriptor) => string;

/*
 * `printer-state-reasons` keywords (severity suffix already removed by the hub) and the two
 * hub codes that reach the same places (`not_accepting` on a failed page job).
 * These are state words, not actions, and lower case on purpose: they follow "Stopped".
 */
const WORDS: Record<string, MessageDescriptor> = {
  "toner-empty": msg`toner empty`,
  "toner-low": msg`toner low`,
  "media-empty": msg`media empty`,
  "media-jam": msg`media jam`,
  "door-open": msg`door open`,
  "cover-open": msg`cover open`,
  paused: msg`paused`,
  offline: msg`offline`,
  "marker-supply-empty": msg`supply empty`,
  "marker-supply-low": msg`supply low`,
  "media-low": msg`media low`,
  "unknown-state": msg`state unknown`,
  not_accepting: msg`not accepting jobs`,
};

/** The words for a keyword; a keyword the hub sent but we have no words for stays verbatim. */
export function reasonWord(keyword: string, t: Translate): string {
  const descriptor = Object.hasOwn(WORDS, keyword) ? WORDS[keyword] : undefined;
  return descriptor ? t(descriptor) : keyword;
}

/** True when `reasonWord` has real words for the keyword (an unknown one is returned unchanged). */
export const isKnownReason = (keyword: string): boolean => Object.hasOwn(WORDS, keyword);

/** `reasonWord` bound to the active language, for components. */
export function useReasonWord(): (keyword: string) => string {
  const { _ } = useLingui();
  return (keyword) => reasonWord(keyword, _);
}
