import { i18n } from "@lingui/core";
import { msg } from "@lingui/core/macro";
import { useLingui } from "@lingui/react";
import { useLingui as useMacroLingui } from "@lingui/react/macro";
import type { ContentType, LookupApp } from "./cart";

export const LOOKUP_APPS: readonly LookupApp[] = ["snipeit", "grocy", "spoolman"];
export const isLookupApp = (value: string): value is LookupApp => (LOOKUP_APPS as readonly string[]).includes(value);

/** The same mapping as the QR landing paths in `backend/app/api/routes/qr.py`. */
export const QR_PATH_APP = { loc: "snipeit", asset: "snipeit", spool: "spoolman", product: "grocy" } as const satisfies Record<string, LookupApp>;

/** Layouts a looked-up item can be printed with (a label needs a title, a code and a link). */
export const LOOKUP_CONTENT_TYPES: readonly ContentType[] = [
  "qr_two_lines",
  "qr_one_line",
  "qr_three_lines",
  "qr_only",
  "text_two_lines",
  "text_one_line",
];
export const DEFAULT_CONTENT_TYPE: ContentType = "qr_two_lines";

const APP_NAMES = { snipeit: msg`Snipe-IT`, grocy: msg`Grocy`, spoolman: msg`Spoolman` };

/** For code outside React (search sources); components use `useAppName`. */
export const appNameOf = (app: LookupApp): string => i18n._(APP_NAMES[app]);

export function useAppName(): (app: LookupApp) => string {
  const { _ } = useLingui();
  return (app) => _(APP_NAMES[app]);
}

export function useContentTypeLabel(): (type: ContentType) => string {
  const { t } = useMacroLingui();
  return (type) => {
    switch (type) {
      case "qr_two_lines":
        return t`QR code, code and title`;
      case "qr_one_line":
        return t`QR code and code`;
      case "qr_three_lines":
        return t`QR code, code, title and detail`;
      case "qr_only":
        return t`QR code only`;
      case "text_two_lines":
        return t`Code and title, no QR code`;
      case "text_one_line":
        return t`Code only, no QR code`;
      default:
        return type;
    }
  };
}

/** Only web links become links: the URL comes from another system. */
export function safeHref(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    const parsed = new URL(url);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.href : null;
  } catch {
    return null;
  }
}

/** `12mm laminated …` -> 12; the preview needs a tape width and 12 is the common one. */
export function tapeMmOf(tapeLoaded: string | null | undefined): number {
  const match = /^\s*(\d+)\s*mm/i.exec(tapeLoaded ?? "");
  return match ? Number(match[1]) : 12;
}
