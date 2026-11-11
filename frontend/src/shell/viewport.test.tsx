import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { listRoom, perFrame, readViewport, sameRoom, subscribeViewport, trackVisibleViewport } from "./viewport";

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

beforeEach(() => {
  install(new FakeViewport());
});
afterEach(() => {
  document.documentElement.removeAttribute("style");
  document.body.innerHTML = "";
});
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
});

describe("perFrame", () => {
  it("runs once per frame however often it is asked, and not after cancel", () => {
    const frames: FrameRequestCallback[] = [];
    vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => frames.push(cb));
    vi.stubGlobal("cancelAnimationFrame", (id: number) => {
      frames[id - 1] = () => {};
    });
    const fn = vi.fn();
    const frame = perFrame(fn);
    frame.run();
    frame.run();
    frame.run();
    frames.splice(0).forEach((cb) => cb(0));
    expect(fn).toHaveBeenCalledTimes(1);
    frame.run();
    frame.cancel();
    frames.splice(0).forEach((cb) => cb(0));
    expect(fn).toHaveBeenCalledTimes(1);
    frame.run();
    frames.splice(0).forEach((cb) => cb(0));
    expect(fn).toHaveBeenCalledTimes(2);
    vi.unstubAllGlobals();
  });
});

describe("sameRoom", () => {
  it("compares placement and height", () => {
    expect(sameRoom({ placement: "bottom start", maxHeight: 100 }, { placement: "bottom start", maxHeight: 100 })).toBe(true);
    expect(sameRoom({ placement: "bottom start", maxHeight: 100 }, { placement: "top start", maxHeight: 100 })).toBe(false);
    expect(sameRoom({ placement: "bottom start", maxHeight: 100 }, { placement: "bottom start", maxHeight: 99 })).toBe(false);
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
