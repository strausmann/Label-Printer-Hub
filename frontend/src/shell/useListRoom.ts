// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useEffect, useRef, useState, type RefObject } from "react";
import { listRoom, perFrame, readViewport, sameRoom, subscribeViewport, type ListRoom } from "./viewport";

/** The tallest a list gets (px) and the gap it keeps to the screen edge and the tab bar. */
export const LIST_MAX = 384;
export const LIST_GAP = 12;
/** The least height of one option (px): about four of them must fit below a field, else the list opens above. */
const OPTION = 44;
/** What a field sits in when it is in a dialog. */
const DIALOG = '[role="dialog"], [role="alertdialog"]';

/**
 * Where the list of a field goes and how tall it may get, measured against what is visible.
 *
 * React Aria measures against the whole page, not the screen, so a list would run past the bottom edge, under the fixed
 * tab bar of a phone and under the on-screen keyboard. `measure()` reads the anchor, the visible area and (outside a
 * dialog) the top of the tab bar; call it when the list opens. While `open`, the hook measures again once per frame
 * whenever the visible area changes, because the keyboard can come up after the list opened.
 */
export function useListRoom(anchor: RefObject<HTMLElement | null>, open: boolean): { room: ListRoom; measure: () => void } {
  const [room, setRoom] = useState<ListRoom>({ placement: "bottom start", maxHeight: LIST_MAX });
  const measure = () => {
    const el = anchor.current;
    if (!el) return;
    // The tab bar limits the list, but not inside a dialog: the dialog covers it, and with the keyboard open the bar
    // sits right above the keyboard, so counting it would take a strip of the room off for nothing.
    const bar = el.closest(DIALOG) ? null : document.querySelector("[data-tabbar]");
    // The topmost box of the bar and its children: the raised Scan button sticks out above the bar itself.
    const lowest = bar && getComputedStyle(bar).display !== "none" ? Math.min(...[bar, ...Array.from(bar.children)].map((n) => n.getBoundingClientRect().top)) : undefined;
    const next = listRoom(el.getBoundingClientRect(), readViewport(), { lowest, gap: LIST_GAP, max: LIST_MAX, option: OPTION });
    setRoom((prev) => (sameRoom(prev, next) ? prev : next));
  };
  const latest = useRef(measure);
  useEffect(() => {
    latest.current = measure;
  });
  useEffect(() => {
    if (!open) return;
    const again = perFrame(() => latest.current());
    const stop = subscribeViewport(again.run);
    return () => {
      stop();
      again.cancel();
    };
  }, [open]);
  return { room, measure };
}
