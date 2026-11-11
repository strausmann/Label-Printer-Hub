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

/**
 * Publishes the visible area as `--vvh` (height) and `--vv-top` (offset) on `root` and keeps them current.
 * Returns the function that takes it all down again.
 *
 * It does not scroll the focused field into view: the browsers do that themselves when the keyboard opens, and a second
 * scroll from here moves pages that a person (or a screenshot tool resizing the window) did not ask to move.
 */
export function trackVisibleViewport(root: HTMLElement = document.documentElement, win: Win = window): () => void {
  const publish = () => {
    const { height, offsetTop } = readViewport(win);
    root.style.setProperty("--vvh", `${height}px`);
    root.style.setProperty("--vv-top", `${offsetTop}px`);
  };
  publish();
  const stop = subscribeViewport(publish, win);
  return () => {
    stop();
    root.style.removeProperty("--vvh");
    root.style.removeProperty("--vv-top");
  };
}

/**
 * Runs `fn` at most once per animation frame, however many events ask for it (the window and the visual viewport both
 * report one resize; iOS reports a scroll of the visual viewport continuously).
 */
export function perFrame(fn: () => void): { run: () => void; cancel: () => void } {
  let frame = 0;
  return {
    run: () => {
      if (frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        fn();
      });
    },
    cancel: () => {
      if (frame) cancelAnimationFrame(frame);
      frame = 0;
    },
  };
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

/** Do two rooms say the same? (`setRoom` keeps the old object then, and nothing re-renders.) */
export const sameRoom = (a: ListRoom, b: ListRoom) => a.placement === b.placement && a.maxHeight === b.maxHeight;
