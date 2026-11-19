// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { afterEach, describe, expect, it } from "vitest";
import {
  canStartPull,
  insideInnerScroller,
  isStandalone,
  isTextField,
  lockDirection,
  PULL_MAX,
  PULL_THRESHOLD,
  pullDistance,
  pullOutcome,
  type PullStart,
} from "./pullToRefresh";

const GOOD: PullStart = { scrollY: 0, standalone: true, dialogOpen: false, textFieldFocused: false, insideScroller: false, pendingWrites: 0 };

describe("canStartPull", () => {
  it("starts at the top in the installed app", () => {
    expect(canStartPull(GOOD)).toBe(true);
  });
  it("a page scrolled down never pulls", () => {
    expect(canStartPull({ ...GOOD, scrollY: 1 })).toBe(false);
  });
  it("a touch inside an inner scroll area never pulls", () => {
    expect(canStartPull({ ...GOOD, insideScroller: true })).toBe(false);
  });
  it("an open dialog never pulls", () => {
    expect(canStartPull({ ...GOOD, dialogOpen: true })).toBe(false);
  });
  it("a focused text field never pulls", () => {
    expect(canStartPull({ ...GOOD, textFieldFocused: true })).toBe(false);
  });
  it("a pending write never pulls", () => {
    expect(canStartPull({ ...GOOD, pendingWrites: 1 })).toBe(false);
  });
  it("the browser tab never uses the own gesture", () => {
    expect(canStartPull({ ...GOOD, standalone: false })).toBe(false);
  });
});

describe("the numbers of the gesture", () => {
  it("the first move locks the direction", () => {
    expect(lockDirection(30, 20)).toBe("abandon");
    expect(lockDirection(5, 20)).toBe("pull");
    expect(lockDirection(20, 20)).toBe("abandon");
    expect(lockDirection(0, -10)).toBe("abandon"); // upwards is a scroll, not a pull
  });
  it("the distance is half the finger travel, capped at 112", () => {
    expect(pullDistance(100)).toBe(50);
    expect(pullDistance(400)).toBe(PULL_MAX);
    expect(pullDistance(-10)).toBe(0);
    expect(PULL_MAX).toBe(112);
  });
  it("72 reloads, 71 cancels", () => {
    expect(PULL_THRESHOLD).toBe(72);
    expect(pullOutcome(72)).toBe("reload");
    expect(pullOutcome(71)).toBe("cancel");
  });
});

/** jsdom lays nothing out: the sizes a browser would report are set by hand. */
function box(style: Partial<CSSStyleDeclaration>, size: { sh?: number; ch?: number; sw?: number; cw?: number } = {}) {
  const el = document.createElement("div");
  Object.assign(el.style, style);
  Object.defineProperty(el, "scrollHeight", { value: size.sh ?? 0, configurable: true });
  Object.defineProperty(el, "clientHeight", { value: size.ch ?? 0, configurable: true });
  Object.defineProperty(el, "scrollWidth", { value: size.sw ?? 0, configurable: true });
  Object.defineProperty(el, "clientWidth", { value: size.cw ?? 0, configurable: true });
  return el;
}

describe("insideInnerScroller", () => {
  afterEach(() => {
    document.body.innerHTML = "";
  });
  const mount = (el: HTMLElement) => {
    const leaf = document.createElement("span");
    el.append(leaf);
    document.body.append(el);
    return leaf;
  };
  it("is true below a scrollable overflow-y: auto ancestor", () => {
    expect(insideInnerScroller(mount(box({ overflowY: "auto" }, { sh: 500, ch: 200 })), document.documentElement)).toBe(true);
  });
  it("is true below an overflow-x: auto ancestor that is wider than it shows", () => {
    expect(insideInnerScroller(mount(box({ overflowX: "auto" }, { sw: 900, cw: 300 })), document.documentElement)).toBe(true);
  });
  it("is false for an ancestor that cannot scroll on either axis", () => {
    expect(insideInnerScroller(mount(box({ overflow: "auto" }, { sh: 200, ch: 200, sw: 300, cw: 300 })), document.documentElement)).toBe(false);
  });
  it("is false for overflow: visible, however large the content", () => {
    expect(insideInnerScroller(mount(box({ overflow: "visible" }, { sh: 900, ch: 100, sw: 900, cw: 100 })), document.documentElement)).toBe(false);
  });
  it("does not look above the stop element", () => {
    const outer = box({ overflowY: "auto" }, { sh: 500, ch: 200 });
    const stop = document.createElement("div");
    outer.append(stop);
    const leaf = document.createElement("span");
    stop.append(leaf);
    document.body.append(outer);
    expect(insideInnerScroller(leaf, stop)).toBe(false);
  });
  it("is false without a target", () => {
    expect(insideInnerScroller(null, document.documentElement)).toBe(false);
  });
});

describe("isTextField", () => {
  const input = (type?: string) => {
    const el = document.createElement("input");
    if (type) el.type = type;
    return el;
  };
  it.each(["text", "search", "number", "email", "password"])("is true for an input of type %s", (type) => {
    expect(isTextField(input(type))).toBe(true);
  });
  it("is true for a textarea and for contenteditable", () => {
    expect(isTextField(document.createElement("textarea"))).toBe(true);
    const ce = document.createElement("div");
    ce.setAttribute("contenteditable", "true");
    expect(isTextField(ce)).toBe(true);
  });
  it("is false for a checkbox, a button and nothing", () => {
    expect(isTextField(input("checkbox"))).toBe(false);
    expect(isTextField(document.createElement("button"))).toBe(false);
    expect(isTextField(null)).toBe(false);
  });
});

describe("isStandalone", () => {
  const win = (matches: boolean, standalone?: boolean) =>
    ({ matchMedia: (q: string) => ({ matches: matches && q === "(display-mode: standalone)" }), navigator: { standalone } }) as unknown as Window;
  it("reads display-mode: standalone", () => {
    expect(isStandalone(win(true))).toBe(true);
    expect(isStandalone(win(false))).toBe(false);
  });
  it("reads navigator.standalone (Safari on iOS)", () => {
    expect(isStandalone(win(false, true))).toBe(true);
  });
  it("is false where the browser has no matchMedia", () => {
    expect(isStandalone({ navigator: {} } as unknown as Window)).toBe(false);
  });
});
