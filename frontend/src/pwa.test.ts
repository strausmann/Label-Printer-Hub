import { describe, expect, it } from "vitest";
import { pwaOptions } from "../pwa.config";

const workbox = pwaOptions.workbox!;

describe("pwa", () => {
  it("service worker never caches /api", () => {
    expect(workbox.navigateFallback).toBe("/index.html");
    const deny = workbox.navigateFallbackDenylist ?? [];
    for (const path of ["/api/v1/jobs", "/api/v1/auth/session", "/docs", "/openapi.json", "/docs/oauth2-redirect"]) {
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
    // A new worker waits for the person to reload instead of replacing files an open tab still loads.
    expect(pwaOptions.registerType).toBe("prompt");
    expect(workbox.skipWaiting).toBe(false);
    const precached = workbox.globPatterns ?? [];
    expect(precached.join(" ")).not.toMatch(/\/api\//);
  });

  it("leaves the licence texts to the server: the About page's licence link opens the text, not the app", () => {
    // AGPL section 13: the installed app must hand out its licence. /licenses/*.txt is not precached, so
    // without this entry the navigation fallback answers the About page's link with index.html.
    const deny = workbox.navigateFallbackDenylist ?? [];
    for (const path of ["/licenses/agpl-3.0.txt", "/licenses/"]) {
      expect(
        deny.some((re) => re.test(path)),
        path,
      ).toBe(true);
    }
    expect(deny.some((re) => re.test("/licensesx"))).toBe(false);
  });

  it("serves its manifest as a plain file, not a generated one", () => {
    // The manifest is public/manifest.webmanifest, linked from index.html; what the build really emits
    // (the built shell and the manifest next to it) is checked in build.test.ts.
    expect(pwaOptions.manifest).toBe(false);
  });
});
