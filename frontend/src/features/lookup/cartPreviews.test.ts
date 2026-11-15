// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { describe, expect, it } from "vitest";
import type { CartItem, ContentType } from "./cart";
import { checkChunks, distinctPreviews, MAX_CART_PREVIEWS } from "./cartPreviews";

const item = (id: string, content_type: ContentType): CartItem => ({ app: "snipeit", id, name: `Item ${id}`, content_type, copies: 1 });

describe("distinctPreviews", () => {
  it("shows the first item of each content type", () => {
    const list = [item("1", "qr_two_lines"), item("2", "qr_two_lines"), item("3", "qr_only")];
    const { shown, hiddenTypes } = distinctPreviews(list);
    expect(shown.map((i) => i.id)).toEqual(["1", "3"]);
    expect(hiddenTypes).toBe(0);
  });

  it("caps the previews and counts the content types left out", () => {
    const types: ContentType[] = ["qr_only", "qr_one_line", "qr_two_lines", "qr_three_lines", "text_one_line", "text_two_lines"];
    const { shown, hiddenTypes } = distinctPreviews(types.map((type, n) => item(String(n), type)));
    expect(MAX_CART_PREVIEWS).toBe(4);
    expect(shown).toHaveLength(4);
    expect(hiddenTypes).toBe(2);
  });

  it("keeps the order of the cart", () => {
    const { shown } = distinctPreviews([item("1", "text_one_line"), item("2", "qr_only"), item("3", "text_one_line")]);
    expect(shown.map((i) => i.id)).toEqual(["1", "2"]);
  });

  it("answers an empty cart with nothing", () => {
    expect(distinctPreviews([])).toEqual({ shown: [], hiddenTypes: 0 });
  });
});

describe("checkChunks", () => {
  it("chunks a cart of 120 items into three requests", () => {
    const list = Array.from({ length: 120 }, (_, n) => item(String(n), "qr_only"));
    expect(checkChunks(list).map((c) => c.length)).toEqual([50, 50, 20]);
  });

  it("makes no request for an empty cart", () => {
    expect(checkChunks([])).toEqual([]);
  });
});
