import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { pwaOptions } from "../pwa.config";

const workbox = pwaOptions.workbox!;

const PUBLIC = resolve(__dirname, "..", "public");
const BRAND = resolve(__dirname, "..", "..", "docs", "brand", "labelyard");

type Icon = { src: string };
type Manifest = {
  name: string;
  short_name: string;
  description: string;
  id: string;
  icons: Icon[];
  shortcuts: { icons?: Icon[] }[];
};
const manifest = JSON.parse(readFileSync(resolve(PUBLIC, "manifest.webmanifest"), "utf8")) as Manifest;

// docs/brand/labelyard/ is the source of truth; these are copies of it (source file -> path under public/).
const BRAND_COPIES: [string, string][] = [
  ["mark.svg", "brand/mark.svg"],
  ["mark-dark.svg", "brand/mark-dark.svg"],
  ["mark-mono.svg", "brand/mark-mono.svg"],
  ["wordmark.svg", "brand/wordmark.svg"],
  ["social-card.png", "brand/social-card.png"],
  ["favicon.svg", "favicon.svg"],
  ["favicon.ico", "favicon.ico"],
  ["favicon-16.png", "favicon-16.png"],
  ["favicon-32.png", "favicon-32.png"],
  ["apple-touch-icon.png", "apple-touch-icon.png"],
  ["icon-192.png", "icon-192.png"],
  ["icon-512.png", "icon-512.png"],
  ["icon-maskable-512.png", "icon-maskable-512.png"],
];

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

  it("does not precache the brand files the app never shows", () => {
    const ignored = workbox.globIgnores ?? [];
    expect(ignored).toEqual(expect.arrayContaining(["brand/social-card.png", "brand/mark-mono.svg", "favicon-16.png", "favicon-32.png"]));
  });

  it("carries the Labelyard name", () => {
    expect(manifest.name).toBe("Labelyard");
    expect(manifest.short_name).toBe("Labelyard");
    // Longer short names are cut off under the home-screen icon.
    expect(manifest.short_name.length).toBeLessThanOrEqual(12);
    expect(manifest.description).toBe("Label Printer Hub — print labels, scan codes and watch your label printers.");
    expect(manifest.id).toBe("/");
  });

  it("every manifest icon exists", () => {
    const icons = [...manifest.icons, ...manifest.shortcuts.flatMap((s) => s.icons ?? [])];
    expect(icons.length).toBeGreaterThan(0);
    for (const icon of icons) {
      expect(existsSync(resolve(PUBLIC, icon.src.replace(/^\//, ""))), icon.src).toBe(true);
    }
  });

  it("index.html names the app and links the favicon", () => {
    const html = readFileSync(resolve(__dirname, "..", "index.html"), "utf8");
    expect(html).toContain("<title>Labelyard</title>");
    expect(html).toContain('href="/favicon.svg"');
    expect(html).toContain('href="/favicon.ico"');
  });

  it("brand copies match docs/brand/labelyard", () => {
    for (const [source, copy] of BRAND_COPIES) {
      const original = readFileSync(resolve(BRAND, source));
      const target = resolve(PUBLIC, copy);
      const copied = existsSync(target) ? readFileSync(target) : Buffer.alloc(0);
      expect(copied.equals(original), `public/${copy} is not a copy of docs/brand/labelyard/${source}`).toBe(true);
    }
  });
});
