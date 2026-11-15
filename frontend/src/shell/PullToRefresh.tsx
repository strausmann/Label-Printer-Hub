// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useIsMutating } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { canStartPull, insideInnerScroller, isStandalone, isTextField, lockDirection, PULL_THRESHOLD, pullDistance, pullOutcome, reloadApp } from "./pullToRefresh";

type Phase = "idle" | "undecided" | "pulling";
const reducedMotion = () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;

/**
 * Pull down at the top of a page to reload it, in the installed app only (#331). A browser tab keeps the browser's own
 * gesture, so nothing is registered there.
 *
 * It stays out of the way: it never starts below the top, inside a list or grid that scrolls, behind a dialog, in a
 * text field or while a write is in flight, and a first move that is more sideways than down is left alone for good.
 */
export function PullToRefresh() {
  const [standalone] = useState(() => isStandalone());
  const pending = useIsMutating();
  const pendingRef = useRef(pending);
  useEffect(() => {
    pendingRef.current = pending;
  }, [pending]);
  const [pull, setPull] = useState({ distance: 0, reloading: false });

  useEffect(() => {
    if (!standalone) return;
    const root = document.documentElement;
    root.dataset.standalone = "";
    let phase: Phase = "idle";
    let startX = 0;
    let startY = 0;
    let distance = 0;

    const reset = () => {
      phase = "idle";
      distance = 0;
      setPull((p) => (p.distance === 0 || p.reloading ? p : { distance: 0, reloading: false }));
    };
    const onStart = (event: TouchEvent) => {
      if (event.touches.length > 1) return reset(); // a second finger is a pinch or something else
      const touch = event.touches[0];
      const ok = canStartPull({
        scrollY: window.scrollY,
        standalone: true,
        dialogOpen: document.querySelector('[role="dialog"], [role="alertdialog"]') !== null,
        textFieldFocused: isTextField(document.activeElement),
        insideScroller: insideInnerScroller(event.target instanceof Element ? event.target : null, root),
        pendingWrites: pendingRef.current,
      });
      if (!ok || !touch) return reset();
      phase = "undecided";
      startX = touch.clientX;
      startY = touch.clientY;
      distance = 0;
    };
    const onMove = (event: TouchEvent) => {
      if (phase === "idle") return;
      if (event.touches.length > 1) return reset();
      const touch = event.touches[0];
      if (!touch) return;
      const dx = touch.clientX - startX;
      const dy = touch.clientY - startY;
      if (phase === "undecided") {
        if (dx === 0 && dy === 0) return;
        if (lockDirection(dx, dy) === "abandon") {
          phase = "idle"; // decided once, for the whole touch
          return;
        }
        phase = "pulling";
      }
      if (event.cancelable) event.preventDefault(); // the browser must not scroll or bounce under the indicator
      distance = pullDistance(dy);
      setPull({ distance, reloading: false });
    };
    const onEnd = () => {
      if (phase !== "pulling") return reset();
      const outcome = pullOutcome(distance);
      phase = "idle";
      if (outcome === "reload") {
        setPull({ distance, reloading: true });
        reloadApp();
      } else {
        reset();
      }
    };

    document.addEventListener("touchstart", onStart, { passive: true });
    document.addEventListener("touchmove", onMove, { passive: false });
    document.addEventListener("touchend", onEnd);
    document.addEventListener("touchcancel", reset);
    return () => {
      document.removeEventListener("touchstart", onStart);
      document.removeEventListener("touchmove", onMove);
      document.removeEventListener("touchend", onEnd);
      document.removeEventListener("touchcancel", reset);
      delete root.dataset.standalone;
    };
  }, [standalone]);

  if (!standalone) return null;
  const visible = pull.distance > 0 || pull.reloading;
  const armed = pull.distance >= PULL_THRESHOLD;
  const still = reducedMotion();
  // Follows the finger from above the edge; under reduced motion it only fades in place.
  const travel = still ? 0 : pull.distance - 44;
  const progress = Math.min(1, pull.distance / PULL_THRESHOLD);
  return (
    <div
      aria-hidden="true"
      data-testid="pull-indicator"
      data-armed={armed ? "true" : "false"}
      data-reloading={pull.reloading ? "true" : undefined}
      className="pointer-events-none fixed inset-x-0 z-40 flex justify-center"
      style={{ top: "env(safe-area-inset-top)", opacity: visible ? 1 : 0, transform: still ? undefined : `translateY(${travel}px)` }}
    >
      <span
        className={`flex size-11 items-center justify-center rounded-full border border-line bg-surface shadow-md transition-colors duration-150 ${armed ? "text-link" : "text-ink-3"}`}
      >
        <svg
          viewBox="0 0 24 24"
          width="22"
          height="22"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.75"
          strokeLinecap="round"
          strokeLinejoin="round"
          className={pull.reloading ? "animate-spin motion-reduce:animate-none" : undefined}
          style={still || pull.reloading ? undefined : { transform: `rotate(${progress * 270}deg)` }}
        >
          <path d="M20 12a8 8 0 1 1-2.6-5.9" />
          <path d="M20 4v5h-5" />
        </svg>
      </span>
    </div>
  );
}
