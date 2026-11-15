// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { QueryClient, QueryClientProvider, useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type * as Actual from "./pullToRefresh";
import { PullToRefresh } from "./PullToRefresh";
import * as ptr from "./pullToRefresh";

vi.mock("./pullToRefresh", async (importActual) => ({ ...(await importActual<typeof Actual>()), reloadApp: vi.fn() }));

let standalone = true;
let reduced = false;
beforeEach(() => {
  standalone = true;
  reduced = false;
  vi.mocked(ptr.reloadApp).mockClear();
  window.matchMedia = ((query: string) => ({
    matches: query === "(display-mode: standalone)" ? standalone : query === "(prefers-reduced-motion: reduce)" ? reduced : false,
    media: query,
    addEventListener() {},
    removeEventListener() {},
  })) as unknown as typeof window.matchMedia;
});
afterEach(() => {
  delete (window as { matchMedia?: unknown }).matchMedia;
});

type Pt = [number, number];
/** jsdom has no Touch: an event that carries the one property the gesture reads. */
function touch(type: string, points: Pt[], target: EventTarget = document.body) {
  const event = new Event(type, { bubbles: true, cancelable: true });
  Object.defineProperty(event, "touches", { value: points.map(([clientX, clientY]) => ({ clientX, clientY })) });
  act(() => {
    target.dispatchEvent(event);
  });
  return event;
}
const indicator = () => screen.queryByTestId("pull-indicator");

function Holder({ children }: { children?: React.ReactNode }) {
  return <>{children}</>;
}
function Mount({ children }: { children?: React.ReactNode }) {
  const [client] = useState(() => new QueryClient());
  return (
    <QueryClientProvider client={client}>
      <PullToRefresh />
      <Holder>{children}</Holder>
    </QueryClientProvider>
  );
}

describe("PullToRefresh", () => {
  it("a pull past the threshold reloads once", () => {
    render(<Mount />);
    touch("touchstart", [[100, 100]]);
    touch("touchmove", [[100, 160]]);
    touch("touchmove", [[100, 260]]); // 160 px down = 80 px of pull
    expect(indicator()).toHaveAttribute("data-armed", "true");
    touch("touchend", []);
    expect(ptr.reloadApp).toHaveBeenCalledTimes(1);
    touch("touchend", []);
    expect(ptr.reloadApp).toHaveBeenCalledTimes(1);
  });

  it("the pull takes the touch away from the browser", () => {
    render(<Mount />);
    touch("touchstart", [[100, 100]]);
    expect(touch("touchmove", [[100, 130]]).defaultPrevented).toBe(true);
  });

  it("a pull released early does not reload and hides the indicator", () => {
    render(<Mount />);
    touch("touchstart", [[100, 100]]);
    touch("touchmove", [[100, 180]]); // 40 px of pull
    expect(indicator()!.style.opacity).toBe("1");
    expect(indicator()).toHaveAttribute("data-armed", "false");
    touch("touchend", []);
    expect(ptr.reloadApp).not.toHaveBeenCalled();
    expect(indicator()!.style.opacity).toBe("0");
  });

  it("a sideways first move never shows the indicator, even when the finger later goes down", () => {
    render(<Mount />);
    touch("touchstart", [[100, 100]]);
    const first = touch("touchmove", [[150, 110]]);
    touch("touchmove", [[150, 400]]);
    expect(first.defaultPrevented).toBe(false);
    expect(indicator()!.style.opacity).toBe("0");
    touch("touchend", []);
    expect(ptr.reloadApp).not.toHaveBeenCalled();
  });

  it("touchcancel cancels", () => {
    render(<Mount />);
    touch("touchstart", [[100, 100]]);
    touch("touchmove", [[100, 300]]);
    touch("touchcancel", []);
    touch("touchend", []);
    expect(ptr.reloadApp).not.toHaveBeenCalled();
    expect(indicator()!.style.opacity).toBe("0");
  });

  it("a second finger cancels", () => {
    render(<Mount />);
    touch("touchstart", [[100, 100]]);
    touch("touchmove", [[100, 140]]);
    touch("touchmove", [[100, 300], [200, 300]]);
    touch("touchend", []);
    expect(ptr.reloadApp).not.toHaveBeenCalled();
    expect(indicator()!.style.opacity).toBe("0");
  });

  it("no pull while a mutation is pending", async () => {
    function Writer() {
      const m = useMutation({ mutationFn: () => new Promise<void>(() => {}) });
      return (
        <>
          <button onClick={() => m.mutate()}>save</button>
          {m.isPending && <span>pending</span>}
        </>
      );
    }
    render(
      <Mount>
        <Writer />
      </Mount>,
    );
    await act(async () => {
      screen.getByText("save").click();
    });
    await waitFor(() => expect(screen.getByText("pending")).toBeInTheDocument());
    touch("touchstart", [[100, 100]]);
    const move = touch("touchmove", [[100, 300]]);
    touch("touchend", []);
    expect(move.defaultPrevented).toBe(false);
    expect(ptr.reloadApp).not.toHaveBeenCalled();
  });

  it("no pull from inside an open dialog", () => {
    render(
      <Mount>
        <div role="dialog" aria-label="x" />
      </Mount>,
    );
    touch("touchstart", [[100, 100]]);
    touch("touchmove", [[100, 300]]);
    touch("touchend", []);
    expect(ptr.reloadApp).not.toHaveBeenCalled();
  });

  it("nothing is registered in a browser tab", () => {
    standalone = false;
    const add = vi.spyOn(document, "addEventListener");
    render(<Mount />);
    expect(add.mock.calls.filter(([type]) => String(type).startsWith("touch"))).toHaveLength(0);
    expect(indicator()).toBeNull();
    touch("touchstart", [[100, 100]]);
    touch("touchmove", [[100, 300]]);
    touch("touchend", []);
    expect(ptr.reloadApp).not.toHaveBeenCalled();
    add.mockRestore();
  });

  it("under reduced motion the indicator does not follow the finger", () => {
    reduced = true;
    render(<Mount />);
    touch("touchstart", [[100, 100]]);
    touch("touchmove", [[100, 160]]);
    expect(indicator()!.style.transform).toBe("");
    expect(indicator()).toHaveAttribute("data-armed", "false");
    touch("touchmove", [[100, 260]]);
    expect(indicator()!.style.transform).toBe("");
    expect(indicator()).toHaveAttribute("data-armed", "true");
  });

  it("with motion the indicator follows the finger", () => {
    render(<Mount />);
    touch("touchstart", [[100, 100]]);
    touch("touchmove", [[100, 160]]);
    touch("touchmove", [[100, 200]]); // 100 px down = 50 px of pull
    expect(indicator()!.style.transform).toBe("translateY(6px)");
  });

  it("marks the root as the installed app", () => {
    const { unmount } = render(<Mount />);
    expect(document.documentElement).toHaveAttribute("data-standalone");
    unmount();
    expect(document.documentElement).not.toHaveAttribute("data-standalone");
  });

  it("does not mark the root in a browser tab", () => {
    standalone = false;
    render(<Mount />);
    expect(document.documentElement).not.toHaveAttribute("data-standalone");
  });
});
