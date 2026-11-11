import { useSyncExternalStore } from "react";

/**
 * The part of the page the person can see right now.
 *
 * With the on-screen keyboard open, Chromium (with `interactive-widget=resizes-content`) shrinks the
 * layout viewport itself, but Safari on iOS and older browsers only shrink the *visual* viewport and
 * leave `100dvh`, `fixed` boxes and centred dialogs sized for the full screen. `window.visualViewport`
 * is the one source that is right in both cases, so everything that has to stay in sight reads it.
 */
export interface VisibleViewport {
  /** Height of the visible area in px. */
  height: number;
  /** Distance from the top of the layout viewport to the top of the visible area in px. */
  offsetTop: number;
}

type Win = Pick<Window, "innerHeight" | "addEventListener" | "removeEventListener"> & { visualViewport?: VisualViewport | null };

/** The visible area; the layout viewport when the browser has no `visualViewport`. */
export function readViewport(win: Win = window): VisibleViewport {
  const vv = win.visualViewport;
  return vv ? { height: vv.height, offsetTop: vv.offsetTop } : { height: win.innerHeight, offsetTop: 0 };
}

/** Calls `listener` whenever the visible area changes (keyboard, rotation, pinch-zoom, browser bars). Returns the unsubscribe. */
export function subscribeViewport(listener: () => void, win: Win = window): () => void {
  const vv = win.visualViewport;
  win.addEventListener("resize", listener);
  vv?.addEventListener("resize", listener);
  vv?.addEventListener("scroll", listener);
  return () => {
    win.removeEventListener("resize", listener);
    vv?.removeEventListener("resize", listener);
    vv?.removeEventListener("scroll", listener);
  };
}

/** Is `el` a field the on-screen keyboard types into? */
export function isTextField(el: Element | null): el is HTMLElement {
  if (!(el instanceof HTMLElement)) return false;
  if (el.isContentEditable) return true;
  if (el instanceof HTMLTextAreaElement) return true;
  if (el instanceof HTMLInputElement) return !["button", "checkbox", "radio", "range", "file", "submit", "reset", "image", "color"].includes(el.type);
  return false;
}

/**
 * Publishes the visible area as `--vvh` (height) and `--vv-top` (offset) on `root` and, when it changes
 * while a text field has the focus, scrolls that field into view (the keyboard just took its place).
 * Returns the function that takes it all down again.
 */
export function trackVisibleViewport(root: HTMLElement = document.documentElement, win: Win = window): () => void {
  let frame = 0;
  let lastHeight = readViewport(win).height;
  const publish = () => {
    const { height, offsetTop } = readViewport(win);
    root.style.setProperty("--vvh", `${height}px`);
    root.style.setProperty("--vv-top", `${offsetTop}px`);
    return height;
  };
  const reveal = () => {
    frame = 0;
    const active = root.ownerDocument.activeElement;
    if (isTextField(active) && typeof active.scrollIntoView === "function") active.scrollIntoView({ block: "nearest", inline: "nearest" });
  };
  const onChange = () => {
    const height = publish();
    // Only a change of the height (the keyboard) moves the field; a scroll of the visual viewport does not.
    if (height !== lastHeight && !frame) frame = requestAnimationFrame(reveal);
    lastHeight = height;
  };
  publish();
  const stop = subscribeViewport(onChange, win);
  return () => {
    stop();
    if (frame) cancelAnimationFrame(frame);
    root.style.removeProperty("--vvh");
    root.style.removeProperty("--vv-top");
  };
}

let snapshot: VisibleViewport = readViewport();
function getSnapshot(): VisibleViewport {
  const now = readViewport();
  if (now.height !== snapshot.height || now.offsetTop !== snapshot.offsetTop) snapshot = now;
  return snapshot;
}
const SERVER: VisibleViewport = { height: 0, offsetTop: 0 };

/** The visible area as React state: re-renders when the keyboard opens or closes. */
export function useVisibleViewport(): VisibleViewport {
  return useSyncExternalStore(subscribeViewport, getSnapshot, () => SERVER);
}

/** Where a list beside a field goes and how tall it may get. */
export interface ListRoom {
  placement: "bottom start" | "top start";
  maxHeight: number;
}

/**
 * Room for a list next to a field, measured against what is visible: below the field unless that leaves
 * room for fewer than about four options and above has more. `lowest` is the lowest y (layout viewport) the list may
 * reach besides the visible edge, e.g. the top of a fixed tab bar.
 */
export function listRoom(field: { top: number; bottom: number }, view: VisibleViewport, opts: { lowest?: number; gap: number; max: number; option: number }): ListRoom {
  const bottom = Math.min(view.offsetTop + view.height, opts.lowest ?? Infinity);
  const below = bottom - field.bottom - opts.gap;
  const above = field.top - view.offsetTop - opts.gap;
  const up = below < 4 * opts.option && above > below;
  return { placement: up ? "top start" : "bottom start", maxHeight: Math.max(2 * opts.option, Math.min(opts.max, Math.floor(up ? above : below))) };
}
