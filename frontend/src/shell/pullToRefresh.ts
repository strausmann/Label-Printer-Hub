// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

/**
 * Pull to refresh for the installed app (#331).
 *
 * An installed (standalone) app has no browser chrome and so no browser reload; the own gesture fills that gap. In a
 * browser tab the browser's own pull to refresh stays in charge, which is why the root no longer locks vertical
 * overscroll there. Everything that decides is pure and lives here; `PullToRefresh.tsx` only wires events to it.
 */

import { applyUpdate, updateIsWaiting } from "../app/updates";

/** Distance of the indicator (px, after resistance) at which letting go reloads. */
export const PULL_THRESHOLD = 72;
/** The indicator never travels further than this. */
export const PULL_MAX = 112;
/** The indicator follows the finger at half speed: it feels pulled against something. */
export const PULL_RESISTANCE = 0.5;

/** What is true when a finger goes down. */
export interface PullStart {
  scrollY: number;
  standalone: boolean;
  dialogOpen: boolean;
  textFieldFocused: boolean;
  /** The touch began inside an area that scrolls by itself, on either axis. */
  insideScroller: boolean;
  /** Writes in flight (`useIsMutating`): a reload would drop them. */
  pendingWrites: number;
}

export function canStartPull(s: PullStart): boolean {
  return s.standalone && s.scrollY <= 0 && !s.dialogOpen && !s.textFieldFocused && !s.insideScroller && s.pendingWrites === 0;
}

/** Decided once, on the first move: a pull is clearly more down than sideways. Anything else is somebody else's gesture. */
export function lockDirection(dx: number, dy: number): "pull" | "abandon" {
  return dy > Math.abs(dx) ? "pull" : "abandon";
}

/** How far the indicator has travelled for `dy` px of downward finger travel since `touchstart`. */
export function pullDistance(dy: number): number {
  return Math.min(PULL_MAX, Math.max(0, dy * PULL_RESISTANCE));
}

export function pullOutcome(distance: number): "reload" | "cancel" {
  return distance >= PULL_THRESHOLD ? "reload" : "cancel";
}

const SCROLLING = /^(auto|scroll|overlay)$/;

/** Does `target`, or an ancestor below `stopAt`, scroll by itself (either axis)? Pulling there would fight its scrolling. */
export function insideInnerScroller(target: Element | null, stopAt: Element): boolean {
  for (let el = target; el && el !== stopAt; el = el.parentElement) {
    const style = getComputedStyle(el);
    if (SCROLLING.test(style.overflowY) && el.scrollHeight > el.clientHeight) return true;
    if (SCROLLING.test(style.overflowX) && el.scrollWidth > el.clientWidth) return true;
  }
  return false;
}

export function isStandalone(win: Window = window): boolean {
  const media = win.matchMedia?.("(display-mode: standalone)").matches ?? false;
  return media || (win.navigator as Navigator & { standalone?: boolean }).standalone === true;
}

const NOT_TEXT = new Set(["checkbox", "radio", "button", "submit", "reset", "range", "color", "file", "image", "hidden"]);

/** A field the on-screen keyboard opens for. */
export function isTextField(el: Element | null): boolean {
  if (!el) return false;
  if (el instanceof HTMLTextAreaElement) return true;
  if (el instanceof HTMLInputElement) return !NOT_TEXT.has(el.type);
  const editable = el.closest("[contenteditable]");
  return !!editable && editable.getAttribute("contenteditable") !== "false";
}

/**
 * The one place the gesture and the menu entry both end in (and the update notice, #354, will too).
 *
 * With a new version waiting this applies it: a plain reload would be answered by the old service worker from its
 * precache and show the old app again (see `applyUpdate`). Without one it is a plain reload.
 */
export function reloadApp(): void {
  if (updateIsWaiting()) void applyUpdate();
  else window.location.reload();
}
