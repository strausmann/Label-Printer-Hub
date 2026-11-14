// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import type { VitePWAOptions } from "vite-plugin-pwa";

/**
 * The installable app: a service worker that precaches the app shell (HTML, scripts, styles,
 * fonts, icons and the code reader's WebAssembly) so the installed app opens at once.
 *
 * It never touches the API: no runtime caching, and the navigation fallback skips `/api/`,
 * the interactive docs, the OpenAPI document and the licence texts. A cached answer from the hub (a job state,
 * a printer, an item behind a sign-in) is worse than none.
 */
export const pwaOptions: Partial<VitePWAOptions> = {
  // The manifest is a plain file in public/ and linked from index.html.
  manifest: false,
  // A new version waits until the person reloads (see src/app/updates.ts): forcing it on an open
  // tab would leave that tab without the old hashed files it still loads lazily.
  registerType: "prompt",
  injectRegister: false,
  workbox: {
    globPatterns: ["**/*.{js,css,html,woff2,svg,png,wasm,webmanifest}"],
    // The API reference viewer (/docs) is a 5 MB developer tool, not part of the installable app. The social
    // card and the single-colour mark are brand files for other sites and print, and the PNG favicons are for
    // browsers without SVG favicons; the app itself never shows them.
    globIgnores: ["scalar/**", "brand/social-card.png", "brand/mark-mono.svg", "favicon-16.png", "favicon-32.png"],
    navigateFallback: "/index.html",
    // /licenses/ holds the licence texts the About page links (AGPL section 13); they are not precached,
    // so the fallback would answer that link with the app shell instead of the text.
    navigateFallbackDenylist: [/^\/api\//, /^\/docs(\/|$)/, /^\/openapi\.json$/, /^\/licenses\//],
    runtimeCaching: [],
    cleanupOutdatedCaches: true,
    clientsClaim: true,
    skipWaiting: false,
    // The reader's WebAssembly is the one big file; everything else is far below this.
    maximumFileSizeToCacheInBytes: 3 * 1024 * 1024,
  },
};
