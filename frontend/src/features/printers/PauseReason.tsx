import { useLingui } from "@lingui/react/macro";
import type { Printer } from "./api";

/**
 * Why a printer is paused, in words. Known codes get a sentence; an unknown code is shown
 * verbatim in mono so nobody is told something the hub did not say. Renders nothing for
 * a printer without pause details (e.g. an older hub).
 */
export function PauseReason({ pause }: { pause: Printer["pause"] }) {
  const { t } = useLingui();
  if (!pause) return null;
  const known: Record<string, string> = {
    user: t`Paused by user`,
    tape_empty: t`Tape is empty`,
    cover_open: t`Cover is open`,
    printer_cover_open: t`Cover is open`,
    tape_mismatch: t`Wrong tape loaded`,
    offline: t`Printer is offline`,
    printer_offline: t`Printer is offline`,
  };
  const text = Object.hasOwn(known, pause.reason_code) ? known[pause.reason_code] : null;
  return (
    <span className="text-small text-ink-2">
      {text ?? <code className="font-mono">{pause.reason_code}</code>}
    </span>
  );
}
