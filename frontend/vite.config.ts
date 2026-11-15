// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { lingui } from "@lingui/vite-plugin";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { createViteLicensePlugin } from "rollup-license-plugin";
import { VitePWA } from "vite-plugin-pwa";
import type { Plugin } from "vite";
import { defineConfig } from "vitest/config";
import { EXTRA_RECORDS, extraPackagePaths, checkLicences, loadPolicy, projectName, toCycloneDx, toLicenceList } from "./src/licences/build";
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

// What the web app ships, as a licence list (`licenses/frontend.json`, shown on the About page) and a CycloneDX
// document (`frontend.cdx.json`, for scanners). The build fails on a licence outside licence-policy.yml; the
// image build sets LICENCE_POLICY to the copy it receives. Both files are plain assets: no JSON is precached
// (pwa.config.ts), so neither reaches an installed app. The project itself is not one of its dependencies.
function licenceLists(): Plugin {
  const policy = loadPolicy(process.env.LICENCE_POLICY ?? fileURLToPath(new URL("../licence-policy.yml", import.meta.url)));
  const name = projectName();
  return createViteLicensePlugin({
    outputFilename: false,
    includePackages: extraPackagePaths,
    excludedPackageTest: (packageName) => packageName === name,
    // Judged in checkLicences (name and version known, so a purl exception applies); the plugin sees the string only.
    unacceptableLicenseTest: () => false,
    additionalFiles: {
      "licenses/frontend.json": (packages) => {
        checkLicences(packages, EXTRA_RECORDS, policy);
        return toLicenceList(packages, EXTRA_RECORDS);
      },
      "frontend.cdx.json": (packages) => toCycloneDx(packages, EXTRA_RECORDS, process.env.HUB_VERSION ?? "0.0.0-dev", name),
    },
  });
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
    licenceLists(),
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
