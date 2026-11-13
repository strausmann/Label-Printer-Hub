import { readFileSync } from "node:fs";
import { lingui } from "@lingui/vite-plugin";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";
import type { Plugin } from "vite";
import { defineConfig } from "vitest/config";
import { pwaOptions } from "./pwa.config";

// Licence texts that must travel with the files they cover (OFL-1.1 for the fonts, Apache-2.0 for the
// zxing-cpp code inside the WebAssembly). They are copied into `dist/licenses/` and so into the image.
const NOTICES: { from: string; to: string }[] = [
  { from: "node_modules/@fontsource/atkinson-hyperlegible/LICENSE", to: "licenses/atkinson-hyperlegible-OFL-1.1.txt" },
  { from: "node_modules/@fontsource/atkinson-hyperlegible-mono/LICENSE", to: "licenses/atkinson-hyperlegible-mono-OFL-1.1.txt" },
  { from: "licenses/zxing-cpp-Apache-2.0.txt", to: "licenses/zxing-cpp-Apache-2.0.txt" },
  { from: "licenses/scalar-api-reference-MIT.txt", to: "licenses/scalar-api-reference-MIT.txt" },
];

function licenseNotices(): Plugin {
  return {
    name: "license-notices",
    generateBundle() {
      for (const { from, to } of NOTICES) {
        this.emitFile({ type: "asset", fileName: to, source: readFileSync(new URL(from, import.meta.url), "utf8") });
      }
    },
  };
}

// The interactive API reference (/docs) runs Scalar from the hub itself, never from a CDN. The standalone
// bundle of the pinned @scalar/api-reference package is copied verbatim into `dist/scalar/`; the backend
// serves it at /docs/scalar.js (backend/app/web/api_docs.py). It is not part of the app and not precached.
function scalarApiReference(): Plugin {
  return {
    name: "scalar-api-reference",
    generateBundle() {
      this.emitFile({
        type: "asset",
        fileName: "scalar/standalone.js",
        source: readFileSync(new URL("node_modules/@scalar/api-reference/dist/browser/standalone.js", import.meta.url)),
      });
    },
  };
}

// D1: the backend serves `dist/` — same origin, so the dev server proxies the API.
// The version this bundle is built for. The hub reports its own version on every API response
// (`X-Hub-Version`); when the two differ the open page offers a reload, which loads the new version
// on one click and never by itself (src/app/updates.ts). The image
// build passes `HUB_VERSION` (backend/Dockerfile); both sides default to the same "0.0.0-dev".
const HUB_BUILD_VERSION = process.env.HUB_VERSION || "0.0.0-dev";

export default defineConfig({
  define: { __HUB_BUILD_VERSION__: JSON.stringify(HUB_BUILD_VERSION) },
  plugins: [
    react(),
    lingui({ macroTransform: true }),
    tailwindcss(),
    VitePWA(pwaOptions),
    licenseNotices(),
    scalarApiReference(),
  ],
  server: {
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
  build: { outDir: "dist", sourcemap: false },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test-setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    coverage: {
      provider: "v8",
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/**/*.test.{ts,tsx}", "src/api/schema.gen.ts", "src/main.tsx", "src/vite-env.d.ts", "src/test-setup.ts", "src/features/scan/decoder.worker.ts"],
      thresholds: { lines: 70, functions: 70, branches: 70, statements: 70 },
    },
  },
});
