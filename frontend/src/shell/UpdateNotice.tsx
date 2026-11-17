// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useLingui } from "@lingui/react/macro";
import { useEffect, useLayoutEffect, useState } from "react";
import { applyUpdate, dismissUpdateToast, useUpdateNotice, useUpdating } from "../app/updates";
import { SeverityShape } from "../features/notifications/NotificationCentre";
import { readViewport, subscribeViewport } from "./viewport";

/**
 * How much smaller than the window the visible area must be before the on-screen keyboard counts as open (Safari shrinks
 * only the visual viewport). Browser bars that come and go stay well below it.
 */
export const KEYBOARD_GAP_PX = 120;

const FOCUS = "focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-link";
/** Inputs that open no keyboard. */
const KEYLESS_INPUTS = new Set(["button", "checkbox", "radio", "range", "submit", "reset", "color", "file", "image"]);

/** Does focusing this element open the on-screen keyboard? */
function isTextField(node: EventTarget | null): boolean {
  if (!(node instanceof HTMLElement)) return false;
  if (node instanceof HTMLInputElement) return !KEYLESS_INPUTS.has(node.type);
  if (node instanceof HTMLTextAreaElement || node instanceof HTMLSelectElement) return true;
  return node.isContentEditable || node.closest("[contenteditable]:not([contenteditable=false])") !== null;
}

const coarsePointer = () => window.matchMedia?.("(pointer: coarse)")?.matches ?? false;

/** The visible height, or null while the page is pinch-zoomed (a zoomed visual viewport says nothing about a keyboard). */
function unzoomedHeight(): number | null {
  const scale = window.visualViewport?.scale ?? 1;
  return scale === 1 ? readViewport().height : null;
}

/**
 * Is the on-screen keyboard (probably) open? Chromium shrinks the layout viewport with it, so the heights compare equal
 * there: a focused text field on a touch device counts, until the visible area is back at the height it had when the
 * field got the focus after having shrunk (Android's Back closes the keyboard and leaves the field focused). Safari
 * shrinks only the visual viewport, which is measured against the window. A pinch-zoomed viewport changes nothing.
 */
function useKeyboardUp(): boolean {
  const [typing, setTyping] = useState(() => isTextField(document.activeElement) && coarsePointer());
  const [closedAgain, setClosedAgain] = useState(false);
  const [shrunk, setShrunk] = useState(false);
  useEffect(() => {
    // The visible height when typing began, and whether the keyboard has shrunk it since.
    let typingNow = isTextField(document.activeElement) && coarsePointer();
    let base = unzoomedHeight() ?? window.innerHeight;
    let sawKeyboard = false;
    const measure = () => {
      const height = unzoomedHeight();
      if (height === null) return;
      setShrunk(height < window.innerHeight - KEYBOARD_GAP_PX);
      if (!typingNow) return;
      if (height < base - KEYBOARD_GAP_PX) sawKeyboard = true;
      setClosedAgain(sawKeyboard && height >= base - KEYBOARD_GAP_PX);
    };
    const begin = (next: boolean) => {
      // A move from one field to the next keeps the measure of the first: the keyboard may already be up.
      if (next && !typingNow) {
        base = unzoomedHeight() ?? base;
        sawKeyboard = false;
      }
      typingNow = next;
      setTyping(next);
      setClosedAgain(false);
    };
    const onFocusIn = (event: FocusEvent) => begin(isTextField(event.target) && coarsePointer());
    // Focus that leaves the page (or goes to nothing) has no related target: no field is focused then.
    const onFocusOut = (event: FocusEvent) => begin(isTextField(event.relatedTarget) && coarsePointer());
    document.addEventListener("focusin", onFocusIn);
    document.addEventListener("focusout", onFocusOut);
    measure();
    const stop = subscribeViewport(measure);
    return () => {
      document.removeEventListener("focusin", onFocusIn);
      document.removeEventListener("focusout", onFocusOut);
      stop();
    };
  }, []);
  return (typing && !closedAgain) || shrunk;
}

/**
 * Publishes the toast's height as `--update-toast-h` on the root, so the print toasts stack above it; `0px` while it is
 * not shown.
 */
function usePublishedHeight(node: HTMLElement | null) {
  useLayoutEffect(() => {
    const root = document.documentElement;
    const publish = (height: number) => root.style.setProperty("--update-toast-h", `${Math.round(height)}px`);
    if (!node) {
      publish(0);
      return;
    }
    publish(node.getBoundingClientRect().height);
    if (typeof ResizeObserver === "undefined") return () => publish(0);
    const observer = new ResizeObserver(([entry]) => {
      if (entry) publish(entry.borderBoxSize?.[0]?.blockSize ?? entry.contentRect.height);
    });
    observer.observe(node);
    return () => {
      observer.disconnect();
      publish(0);
    };
  }, [node]);
}

/** The label of a Reload button: "Updating…" while the page gets the new version. */
function useReloadLabel() {
  const { t } = useLingui();
  const updating = useUpdating();
  return { updating, label: updating ? t`Updating…` : t`Reload` };
}

/**
 * A new version waits (#354): a toast at the bottom right (above the tab bar on a phone) until Reload or Later. It never
 * hides itself, and it steps aside while the on-screen keyboard is open, so it never covers the field being typed in.
 */
export function UpdateToast() {
  const { t } = useLingui();
  const notice = useUpdateNotice();
  const keyboardUp = useKeyboardUp();
  const { updating, label } = useReloadLabel();
  const [node, setNode] = useState<HTMLElement | null>(null);
  const shown = notice.waiting && notice.toastOpen && !keyboardUp;
  usePublishedHeight(shown ? node : null);
  if (!shown) return null;
  const version = notice.version;
  return (
    // Escape on the toast is Later, as on the print cards; the keyboard path is the Later button itself.
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions
    <section
      ref={setNode}
      aria-label={t`New version`}
      onKeyDown={(event) => {
        if (event.key === "Escape") dismissUpdateToast();
      }}
      className="update-toast fixed inset-x-4 bottom-[calc(7.5rem+env(safe-area-inset-bottom))] z-30 rounded-r3 px-4 py-3 shadow-lg lg:inset-x-auto lg:right-6 lg:bottom-6 lg:w-[28rem]"
    >
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        {/* Polite: a new version is news, not an error. "Updating…" is read out here, a changed button label is not. */}
        <div role="status" className="flex min-w-0 flex-1 items-start gap-2.5">
          <span className="mt-1.5">
            <SeverityShape severity="warning" />
          </span>
          <span className="flex min-w-0 flex-col">
            <span className="font-bold">{t`New version available`}</span>
            {version && <span className="text-small text-(--toast-ink-2) [overflow-wrap:anywhere]">{t`Version ${version}`}</span>}
            <span className="sr-only">{updating ? t`Updating…` : ""}</span>
          </span>
        </div>
        <div className="ml-auto flex shrink-0 items-center gap-1">
          {/* aria-disabled, not disabled: a disabled button drops the focus to the page. A second press is ignored by applyUpdate. */}
          <button
            type="button"
            onClick={() => void applyUpdate()}
            aria-disabled={updating || undefined}
            className={`press inline-flex h-11 items-center rounded-r2 bg-accent px-4 text-small font-bold text-accent-ink aria-disabled:opacity-60 ${FOCUS}`}
          >
            {label}
          </button>
          <button
            type="button"
            onClick={dismissUpdateToast}
            className={`press inline-flex h-11 items-center rounded-r2 px-3 text-small text-(--toast-ink-2) transition-colors duration-150 hover:text-(--toast-ink) ${FOCUS}`}
          >
            {t`Later`}
          </button>
        </div>
      </div>
    </section>
  );
}

/**
 * The same notice in the sidebar (in the menu on a phone), above the status line: it stays after Later, until the page
 * reloads on the new version. Its button is named "Reload new version", so it is not mistaken for the menu's Reload.
 */
export function UpdateSidebarNotice() {
  const { t } = useLingui();
  const notice = useUpdateNotice();
  const { updating, label } = useReloadLabel();
  if (!notice.waiting) return null;
  const version = notice.version;
  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-2 rounded-r3 border border-accent bg-accent-soft p-3">
      {/* The heading keeps its line; when the button does not fit beside it, the button wraps below (#354, R-354-1). */}
      <div className="flex min-w-fit flex-1 items-start gap-2">
        <span className="mt-1.5">
          <SeverityShape severity="warning" />
        </span>
        <span className="flex min-w-0 flex-col">
          <span className="font-bold whitespace-nowrap text-ink">{t`New version`}</span>
          <span className="text-small text-ink-2 [overflow-wrap:anywhere]">{version ? t`${version} ready` : t`Ready to load`}</span>
        </span>
      </div>
      <button
        type="button"
        onClick={() => void applyUpdate()}
        aria-label={updating ? t`Updating…` : t`Reload new version`}
        aria-disabled={updating || undefined}
        className={`press ml-auto inline-flex h-11 shrink-0 items-center rounded-r2 bg-ink px-3 text-small font-bold text-bg aria-disabled:opacity-60 ${FOCUS}`}
      >
        {label}
      </button>
    </div>
  );
}
