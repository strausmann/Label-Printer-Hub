import type { VitePWAOptions } from "vite-plugin-pwa";

/**
 * The installable app: a service worker that precaches the app shell (HTML, scripts, styles,
 * fonts, icons and the code reader's WebAssembly) so the installed app opens at once.
 *
 * It never touches the API: no runtime caching, and the navigation fallback skips `/api/`,
 * the interactive docs and the OpenAPI document. A cached answer from the hub (a job state,
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
    navigateFallback: "/index.html",
    navigateFallbackDenylist: [/^\/api\//, /^\/docs(\/|$)/, /^\/openapi\.json$/, /^\/redoc(\/|$)/],
    runtimeCaching: [],
    cleanupOutdatedCaches: true,
    clientsClaim: true,
    skipWaiting: false,
    // The reader's WebAssembly is the one big file; everything else is far below this.
    maximumFileSizeToCacheInBytes: 3 * 1024 * 1024,
  },
};
