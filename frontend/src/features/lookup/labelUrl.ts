import { QR_PATH_APP } from "./apps";
import type { LookupApp } from "./cart";

export interface LookupTarget {
  app: LookupApp;
  id: string;
}

type QrPath = keyof typeof QR_PATH_APP;

/** The last two path segments: `/asset/42`, also behind a sub-path or with a trailing slash. */
const LABEL_PATH = /(?:^|\/)(asset|loc|spool|product)\/([^/]+)\/?$/;
const MAX_ID_LENGTH = 200;

/** The `/loc` path is the one label whose id the lookup API only understands with a prefix. */
export const lookupIdFromQrPath = (kind: QrPath, id: string): string => (kind === "loc" ? `loc:${id}` : id);

/**
 * A printed label link (the QR payload of this hub) read as "which item is meant".
 * Only the path counts: the host is whatever the label was printed with, and the result is
 * always an in-app route, never something to navigate to.
 */
export function parseLabelUrl(raw: string): LookupTarget | null {
  const text = raw.trim();
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
  const match = LABEL_PATH.exec(pathname);
  if (!match) return null;
  let id: string;
  try {
    id = decodeURIComponent(match[2]!);
  } catch {
    return null;
  }
  if (id === "" || id.length > MAX_ID_LENGTH) return null;
  const kind = match[1] as QrPath;
  return { app: QR_PATH_APP[kind], id: lookupIdFromQrPath(kind, id) };
}

/**
 * What the start page's field means: a label link wins and names its own app, anything else
 * is an id in the app of the page. Blank input means nothing.
 */
export function resolveInput(app: LookupApp, raw: string): LookupTarget | null {
  const text = raw.trim();
  if (text === "") return null;
  const label = parseLabelUrl(text);
  if (label) return label;
  return { app, id: text.replace(/^loc:/i, "loc:") };
}
