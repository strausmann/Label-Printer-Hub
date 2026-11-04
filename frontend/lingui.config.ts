import { defineConfig } from "@lingui/cli";
import { formatter } from "@lingui/format-po";

// D8: English is the source language and the default for a fresh install.
export default defineConfig({
  sourceLocale: "en",
  locales: ["en", "de"],
  fallbackLocales: { default: "en" },
  catalogs: [
    {
      path: "<rootDir>/src/i18n/locales/{locale}/messages",
      include: ["<rootDir>/src"],
    },
  ],
  format: formatter({ lineNumbers: false }),
  compileNamespace: "ts",
});
