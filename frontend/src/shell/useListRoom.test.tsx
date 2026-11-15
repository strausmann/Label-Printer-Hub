// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LIST_MAX, useListRoom } from "./useListRoom";

/** A stand-in for `window.visualViewport` that a test can resize like a keyboard would. */
class FakeViewport extends EventTarget {
  height = 800;
  offsetTop = 0;
  set(height: number) {
    this.height = height;
    this.dispatchEvent(new Event("resize"));
  }
}

let vv: FakeViewport;
let frames: FrameRequestCallback[];
const runFrames = () => act(() => frames.splice(0).forEach((cb) => cb(0)));

/** An anchor whose rect is the numbers the test chose (jsdom has no layout). */
function anchorAt(top: number, bottom: number, parent: HTMLElement = document.body) {
  const el = document.createElement("div");
  el.getBoundingClientRect = () => ({ top, bottom, left: 0, right: 100, width: 100, height: bottom - top, x: 0, y: top, toJSON() {} });
  parent.append(el);
  return { current: el };
}
function tabBarAt(top: number, raisedChildTop?: number) {
  const bar = document.createElement("nav");
  bar.setAttribute("data-tabbar", "");
  bar.getBoundingClientRect = () => ({ top, bottom: top + 60, left: 0, right: 390, width: 390, height: 60, x: 0, y: top, toJSON() {} });
  if (raisedChildTop !== undefined) {
    const child = document.createElement("a");
    child.getBoundingClientRect = () => ({ top: raisedChildTop, bottom: raisedChildTop + 60, left: 150, right: 240, width: 90, height: 60, x: 150, y: raisedChildTop, toJSON() {} });
    bar.append(child);
  }
  document.body.append(bar);
}

beforeEach(() => {
  vv = new FakeViewport();
  Object.defineProperty(window, "visualViewport", { configurable: true, value: vv });
  frames = [];
  vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => frames.push(cb));
  vi.stubGlobal("cancelAnimationFrame", (id: number) => {
    frames[id - 1] = () => {};
  });
});
afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

describe("useListRoom", () => {
  it("starts below the anchor at the full height", () => {
    const { result } = renderHook(() => useListRoom(anchorAt(100, 144), false));
    expect(result.current.room).toEqual({ placement: "bottom start", maxHeight: LIST_MAX });
  });

  it("measures below the anchor when there is room", () => {
    const { result } = renderHook(() => useListRoom(anchorAt(100, 144), true));
    act(() => result.current.measure());
    expect(result.current.room).toEqual({ placement: "bottom start", maxHeight: 384 });
  });

  it("flips above when the keyboard leaves less than four options below", () => {
    vv.height = 400;
    const { result } = renderHook(() => useListRoom(anchorAt(300, 344), true));
    act(() => result.current.measure());
    expect(result.current.room.placement).toBe("top start");
    expect(result.current.room.maxHeight).toBe(288);
  });

  it("the tab bar limits the room outside a dialog", () => {
    tabBarAt(500);
    const { result } = renderHook(() => useListRoom(anchorAt(100, 144), true));
    act(() => result.current.measure());
    // 500 (top of the bar) - 144 (anchor bottom) - 12 (gap)
    expect(result.current.room).toEqual({ placement: "bottom start", maxHeight: 344 });
  });

  it("a child that sticks out above the tab bar (the raised Scan button) limits the room", () => {
    tabBarAt(500, 480);
    const { result } = renderHook(() => useListRoom(anchorAt(100, 144), true));
    act(() => result.current.measure());
    // 480 (top of the child) - 144 - 12
    expect(result.current.room).toEqual({ placement: "bottom start", maxHeight: 324 });
  });

  it("a hidden child of the tab bar (zero rect) does not count", () => {
    tabBarAt(500);
    const hidden = document.createElement("div");
    hidden.getBoundingClientRect = () => ({ top: 0, bottom: 0, left: 0, right: 0, width: 0, height: 0, x: 0, y: 0, toJSON() {} });
    document.querySelector("[data-tabbar]")!.append(hidden);
    const { result } = renderHook(() => useListRoom(anchorAt(100, 144), true));
    act(() => result.current.measure());
    // The same room as without the hidden child.
    expect(result.current.room).toEqual({ placement: "bottom start", maxHeight: 344 });
  });

  it("the tab bar is ignored inside a dialog", () => {
    tabBarAt(500);
    const dialog = document.createElement("div");
    dialog.setAttribute("role", "dialog");
    document.body.append(dialog);
    const { result } = renderHook(() => useListRoom(anchorAt(100, 144, dialog), true));
    act(() => result.current.measure());
    expect(result.current.room.maxHeight).toBe(384);
  });

  it("re-measures when the visible area shrinks while open", async () => {
    const { result } = renderHook(() => useListRoom(anchorAt(300, 344), true));
    act(() => result.current.measure());
    expect(result.current.room.placement).toBe("bottom start");
    act(() => vv.set(400));
    await runFrames();
    expect(result.current.room).toEqual({ placement: "top start", maxHeight: 288 });
  });

  it("does not subscribe while closed", () => {
    const add = vi.spyOn(vv, "addEventListener");
    renderHook(() => useListRoom(anchorAt(100, 144), false));
    expect(add).not.toHaveBeenCalled();
  });

  it("stops listening when it closes: every listener it added is removed", () => {
    const add = vi.spyOn(vv, "addEventListener");
    const remove = vi.spyOn(vv, "removeEventListener");
    const anchor = anchorAt(100, 144);
    const { rerender } = renderHook(({ open }) => useListRoom(anchor, open), { initialProps: { open: true } });
    expect(add).toHaveBeenCalledTimes(2);
    rerender({ open: false });
    expect(remove.mock.calls.map((c) => c[0]).sort()).toEqual(add.mock.calls.map((c) => c[0]).sort());
  });

  it("falls back to the layout viewport without visualViewport", () => {
    Object.defineProperty(window, "visualViewport", { configurable: true, value: null });
    vi.stubGlobal("innerHeight", 400);
    const { result } = renderHook(() => useListRoom(anchorAt(300, 344), true));
    act(() => result.current.measure());
    expect(result.current.room).toEqual({ placement: "top start", maxHeight: 288 });
  });
});
