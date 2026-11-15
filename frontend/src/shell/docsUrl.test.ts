// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { describe, expect, it } from "vitest";
import { DOCS_SITE, docsUrl } from "./docsUrl";

describe("docsUrl (the public docs site, in the language of the UI)", () => {
  it("German pages live under /de/", () => {
    expect(docsUrl("using/calibration", "de")).toBe("https://labelyard.app/de/using/calibration/");
  });

  it("English pages have no language segment", () => {
    expect(docsUrl("using/calibration", "en")).toBe("https://labelyard.app/using/calibration/");
  });

  it("an unknown language falls back to the English page", () => {
    expect(docsUrl("using/calibration", "fr")).toBe("https://labelyard.app/using/calibration/");
  });

  it("is built on the site address", () => {
    expect(DOCS_SITE).toBe("https://labelyard.app");
  });
});
