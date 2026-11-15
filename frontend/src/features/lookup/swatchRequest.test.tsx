// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, pngResponse } from "../test-api";
import { usePreviewImage, type LookupResult } from "./api";
import { toBatchItem, type CartItem } from "./cart";

// The spool label is one fixed across image: no direction or preset may travel with it (#346).
const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>
);
const SWATCH = { spool_id: 7, title: "Sunlu PLA+" };
const spoolItem: LookupResult = {
  app: "spoolman",
  id: "7",
  name: "Spool 7",
  url: "https://spoolman.example.invalid/spool/show/7",
  extra: { swatch: SWATCH },
} as LookupResult;

afterEach(() => vi.unstubAllGlobals());

describe("toBatchItem", () => {
  const line = (content_type: CartItem["content_type"]): CartItem => ({ app: "spoolman", id: "7", name: "Spool 7", content_type, copies: 3 });

  it("sends a spool label with its copies only, whatever layout the cart chose", () => {
    expect(toBatchItem(line("spool_swatch"), { orientation: "along", layout_preset: "compact" }).options).toEqual({ copies: 3 });
  });

  it("keeps the chosen layout on every other content type", () => {
    expect(toBatchItem(line("qr_two_lines"), { orientation: "along" }).options).toEqual({ copies: 3, orientation: "along" });
  });
});

describe("usePreviewImage", () => {
  const lastPreview = (calls: { path: string; body: string | undefined }[]) =>
    JSON.parse(calls.filter((c) => c.path === "/api/v1/render/preview").at(-1)!.body!);

  it("asks for a spool label without orientation or preset, with the swatch data", async () => {
    const { calls } = mockApi({ "POST /api/v1/render/preview": () => pngResponse() });
    renderHook(() => usePreviewImage(spoolItem, "spool_swatch", 62, true, { orientation: "along", layout_preset: "compact" }), { wrapper });
    await waitFor(() => expect(calls.some((c) => c.path === "/api/v1/render/preview")).toBe(true));
    const body = lastPreview(calls);
    expect(body).not.toHaveProperty("orientation");
    expect(body).not.toHaveProperty("layout_preset");
    expect(body.data.swatch).toEqual(SWATCH);
  });

  it("passes the layout on for other content types and leaves the swatch out", async () => {
    const { calls } = mockApi({ "POST /api/v1/render/preview": () => pngResponse() });
    renderHook(() => usePreviewImage(spoolItem, "qr_two_lines", 62, true, { orientation: "along" }), { wrapper });
    await waitFor(() => expect(calls.some((c) => c.path === "/api/v1/render/preview")).toBe(true));
    const body = lastPreview(calls);
    expect(body.orientation).toBe("along");
    expect(body.data).not.toHaveProperty("swatch");
  });
});
