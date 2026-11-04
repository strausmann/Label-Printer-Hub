import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { pwaOptions } from "../pwa.config";

const workbox = pwaOptions.workbox!;

describe("pwa", () => {
  it("service worker never caches /api", () => {
    expect(workbox.navigateFallback).toBe("/index.html");
    const deny = workbox.navigateFallbackDenylist ?? [];
    for (const path of ["/api/jobs", "/api/v1/auth/session", "/docs", "/openapi.json", "/redoc", "/docs/oauth2-redirect"]) {
      expect(
        deny.some((re) => re.test(path)),
        path,
      ).toBe(true);
    }
    for (const path of ["/", "/jobs", "/printers/abc", "/asset/42", "/loc/17", "/scan", "/apiary", "/documents"]) {
      expect(
        deny.some((re) => re.test(path)),
        path,
      ).toBe(false);
    }
    // No runtime route at all: the only things the worker ever serves are the precached shell files.
    expect(workbox.runtimeCaching ?? []).toEqual([]);
    const precached = workbox.globPatterns ?? [];
    expect(precached.join(" ")).not.toMatch(/api/);
  });

  it("is installable: standalone manifest with icons", () => {
    // The manifest is a plain file in public/ (served as it is, linked from index.html).
    const m = JSON.parse(readFileSync(resolve(__dirname, "..", "public", "manifest.webmanifest"), "utf8")) as Record<string, unknown>;
    expect(pwaOptions.manifest).toBe(false);
    expect(readFileSync(resolve(__dirname, "..", "index.html"), "utf8")).toContain('rel="manifest" href="/manifest.webmanifest"');
    expect(m.display).toBe("standalone");
    expect(m.start_url).toBe("/");
    expect(m.scope).toBe("/");
    const icons = m.icons as Array<{ sizes: string; purpose?: string }>;
    expect(icons.some((i) => i.sizes === "192x192")).toBe(true);
    expect(icons.some((i) => i.sizes === "512x512")).toBe(true);
    expect(icons.some((i) => i.purpose === "maskable")).toBe(true);
  });
});
