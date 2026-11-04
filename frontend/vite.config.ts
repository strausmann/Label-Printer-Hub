import { lingui } from "@lingui/vite-plugin";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";
import { defineConfig } from "vitest/config";
import { pwaOptions } from "./pwa.config";

// D1: the backend serves `dist/` — same origin, so the dev server proxies the API.
export default defineConfig({
  plugins: [
    react(),
    lingui({ macroTransform: true }),
    tailwindcss(),
    VitePWA(pwaOptions),
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
