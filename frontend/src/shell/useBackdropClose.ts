// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useCallback, useEffect, useRef } from "react";

/**
 * A press that starts and ends on the dimmed area around a dialog closes it, whatever is open inside the dialog (#318).
 *
 * React Aria closes only the top-most overlay on a press outside, and only when that overlay is dismissable. The open list of
 * a combobox is a non-modal popover: it is the top-most overlay but not a dismissable one, so the dialog ignored the press.
 * The press still moved the focus to the page, the dialog's focus scope put it back into the field, the field opened its
 * list again and a phone its keyboard: every tap on the dim area ended where it started. This listens on the dim layer
 * itself, so the stack of overlays has no say, and keeps the focus where it is until the dialog is gone.
 */
export function useBackdropClose(enabled: boolean, onClose: () => void) {
  const latest = useRef(onClose);
  useEffect(() => {
    latest.current = onClose;
  });
  return useCallback(
    (layer: HTMLDivElement | null) => {
      if (!layer || !enabled) return;
      let started = false;
      const down = (event: PointerEvent) => {
        // On the layer itself, not on the dialog or anything inside it.
        started = event.target === layer && event.isPrimary && event.button === 0;
        // No focus move: the browser would take the focus to the page, and the dialog would hand it back to the field.
        if (started) event.preventDefault();
      };
      const up = (event: PointerEvent) => {
        if (started && event.target === layer) latest.current();
        started = false;
      };
      // A touch that turns into a scroll is cancelled, not released: it does not close the dialog.
      const cancel = () => {
        started = false;
      };
      layer.addEventListener("pointerdown", down);
      layer.addEventListener("pointerup", up);
      layer.addEventListener("pointercancel", cancel);
      return () => {
        layer.removeEventListener("pointerdown", down);
        layer.removeEventListener("pointerup", up);
        layer.removeEventListener("pointercancel", cancel);
      };
    },
    [enabled],
  );
}
