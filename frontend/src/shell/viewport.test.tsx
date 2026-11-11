import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { isTextField, listRoom, readViewport, subscribeViewport, trackVisibleViewport, useVisibleViewport } from "./viewport";

/** A stand-in for `window.visualViewport` that a test can resize like a keyboard would. */
class FakeViewport extends EventTarget {
  height = 800;
  offsetTop = 0;
  set(height: number, offsetTop = 0, type: "resize" | "scroll" = "resize") {
    this.height = height;
    this.offsetTop = offsetTop;
    this.dispatchEvent(new Event(type));
  }
}

let vv: FakeViewport | null;
function install(value: FakeViewport | null) {
  vv = value;
  Object.defineProperty(window, "visualViewport", { configurable: true, value });
}
const frames: FrameRequestCallback[] = [];

beforeEach(() => {
  frames.length = 0;
  vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => frames.push(cb));
  vi.stubGlobal("cancelAnimationFrame", (id: number) => {
    frames[id - 1] = () => {};
  });
  install(new FakeViewport());
});
afterEach(() => {
  vi.unstubAllGlobals();
  document.documentElement.removeAttribute("style");
  document.body.innerHTML = "";
});
const runFrames = () => frames.splice(0).forEach((cb) => cb(0));
const listeners = (target: EventTarget) => vi.spyOn(target, "addEventListener");

describe("readViewport", () => {
  it("reads the visual viewport", () => {
    vv!.set(420, 12);
    expect(readViewport()).toEqual({ height: 420, offsetTop: 12 });
  });
  it("falls back to the layout viewport without visualViewport", () => {
    install(null);
    expect(readViewport()).toEqual({ height: window.innerHeight, offsetTop: 0 });
  });
});

describe("subscribeViewport", () => {
  it("listens to resize and scroll of the visual viewport and removes both", () => {
    const listener = vi.fn();
    const stop = subscribeViewport(listener);
    vv!.set(400);
    vv!.set(400, 30, "scroll");
    expect(listener).toHaveBeenCalledTimes(2);
    stop();
    vv!.set(300);
    expect(listener).toHaveBeenCalledTimes(2);
  });
  it("uses the window resize when there is no visualViewport", () => {
    install(null);
    const listener = vi.fn();
    const stop = subscribeViewport(listener);
    window.dispatchEvent(new Event("resize"));
    expect(listener).toHaveBeenCalledTimes(1);
    stop();
    window.dispatchEvent(new Event("resize"));
    expect(listener).toHaveBeenCalledTimes(1);
  });
});

describe("trackVisibleViewport", () => {
  it("publishes --vvh and --vv-top now and on every change", () => {
    const stop = trackVisibleViewport();
    const root = document.documentElement;
    expect(root.style.getPropertyValue("--vvh")).toBe("800px");
    vv!.set(380, 25);
    expect(root.style.getPropertyValue("--vvh")).toBe("380px");
    expect(root.style.getPropertyValue("--vv-top")).toBe("25px");
    stop();
  });
  it("removes the variables and the listeners when stopped", () => {
    const add = listeners(vv!);
    const stop = trackVisibleViewport();
    expect(add).toHaveBeenCalled();
    stop();
    const root = document.documentElement;
    expect(root.style.getPropertyValue("--vvh")).toBe("");
    vv!.set(100);
    expect(root.style.getPropertyValue("--vvh")).toBe("");
  });
  it("works without visualViewport", () => {
    install(null);
    const stop = trackVisibleViewport();
    expect(document.documentElement.style.getPropertyValue("--vvh")).toBe(`${window.innerHeight}px`);
    stop();
  });
  it("scrolls a focused text field into view when the height changes", () => {
    const input = document.createElement("input");
    input.scrollIntoView = vi.fn();
    document.body.append(input);
    input.focus();
    const stop = trackVisibleViewport();
    vv!.set(400);
    runFrames();
    expect(input.scrollIntoView).toHaveBeenCalledWith({ block: "nearest", inline: "nearest" });
    stop();
  });
  it("does not scroll for a pan of the visual viewport, a button or no focus", () => {
    const input = document.createElement("input");
    input.scrollIntoView = vi.fn();
    const button = document.createElement("button");
    button.scrollIntoView = vi.fn();
    document.body.append(input, button);
    const stop = trackVisibleViewport();
    input.focus();
    vv!.set(800, 40, "scroll"); // same height: only panned
    runFrames();
    button.focus();
    vv!.set(400);
    runFrames();
    expect(input.scrollIntoView).not.toHaveBeenCalled();
    expect(button.scrollIntoView).not.toHaveBeenCalled();
    stop();
  });
  it("cancels a pending scroll when stopped", () => {
    const input = document.createElement("input");
    input.scrollIntoView = vi.fn();
    document.body.append(input);
    input.focus();
    const stop = trackVisibleViewport();
    vv!.set(400);
    stop();
    runFrames();
    expect(input.scrollIntoView).not.toHaveBeenCalled();
  });
});

describe("isTextField", () => {
  it("accepts text inputs and textareas, not buttons, checkboxes or null", () => {
    const make = (html: string) => {
      document.body.innerHTML = html;
      return document.body.firstElementChild;
    };
    expect(isTextField(make('<input type="search">'))).toBe(true);
    expect(isTextField(make("<textarea></textarea>"))).toBe(true);
    expect(isTextField(make('<input type="checkbox">'))).toBe(false);
    expect(isTextField(make("<button></button>"))).toBe(false);
    expect(isTextField(null)).toBe(false);
  });
});

describe("useVisibleViewport", () => {
  function Probe() {
    const { height, offsetTop } = useVisibleViewport();
    return <p>{`${height}/${offsetTop}`}</p>;
  }
  it("re-renders when the keyboard opens and closes", () => {
    render(<Probe />);
    expect(screen.getByText("800/0")).toBeInTheDocument();
    act(() => vv!.set(380, 10));
    expect(screen.getByText("380/10")).toBeInTheDocument();
    act(() => vv!.set(800));
    expect(screen.getByText("800/0")).toBeInTheDocument();
  });
});

describe("listRoom", () => {
  const opts = { gap: 12, max: 384, option: 44 };
  it("opens below when there is room for about four options", () => {
    expect(listRoom({ top: 100, bottom: 144 }, { height: 800, offsetTop: 0 }, opts)).toEqual({ placement: "bottom start", maxHeight: 384 });
  });
  it("measures to the bottom of the visible area, not of the screen", () => {
    // 800 px screen, keyboard leaves 400 visible: only 244 px below a field ending at 144.
    const room = listRoom({ top: 100, bottom: 144 }, { height: 400, offsetTop: 0 }, opts);
    expect(room).toEqual({ placement: "bottom start", maxHeight: 244 });
  });
  it("flips above when below holds fewer than four options and above has more", () => {
    const room = listRoom({ top: 300, bottom: 344 }, { height: 400, offsetTop: 0 }, opts);
    expect(room).toEqual({ placement: "top start", maxHeight: 288 });
  });
  it("counts from the top of a panned visual viewport", () => {
    const room = listRoom({ top: 330, bottom: 374 }, { height: 300, offsetTop: 300 }, opts);
    expect(room.placement).toBe("bottom start");
    expect(room.maxHeight).toBe(300 + 300 - 374 - 12);
  });
  it("stops above a fixed bar and never gets smaller than two options", () => {
    expect(listRoom({ top: 100, bottom: 144 }, { height: 800, offsetTop: 0 }, { ...opts, lowest: 500 }).maxHeight).toBe(344);
    expect(listRoom({ top: 20, bottom: 64 }, { height: 70, offsetTop: 0 }, opts).maxHeight).toBe(88);
  });
});
