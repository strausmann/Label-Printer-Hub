// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { describe, expect, it } from "vitest";
import { GROCY_LABEL_TYPES, grocyConfigBlock, grocyLabelKeys, labelPrinterOptions } from "./grocyLabel";

describe("grocyConfigBlock", () => {
  it("gives the four lines of Grocy's config.php for the public URL, without its closing slash", () => {
    expect(grocyConfigBlock("https://hub.example.invalid/")).toBe(
      [
        "Setting('FEATURE_FLAG_LABEL_PRINTER', true);",
        "Setting('LABEL_PRINTER_WEBHOOK', 'https://hub.example.invalid/api/v1/webhook/grocy/label?token=<print-key>');",
        "Setting('LABEL_PRINTER_RUN_SERVER', true);",
        "Setting('LABEL_PRINTER_HOOK_JSON', true);",
      ].join("\n"),
    );
  });

  it("keeps a placeholder when no public URL is set", () => {
    expect(grocyConfigBlock("")).toContain("'<public-url>/api/v1/webhook/grocy/label?token=<print-key>'");
    expect(grocyConfigBlock("   ")).toContain("'<public-url>/api/v1/webhook/grocy/label?token=<print-key>'");
  });

  it("points at the label route with the key as a placeholder", () => {
    expect(grocyConfigBlock("https://hub.example.invalid")).toContain("/api/v1/webhook/grocy/label?token=<print-key>");
  });
});

describe("grocyLabelKeys", () => {
  it("lists the switch, the default printer and a layout and printer per type", () => {
    expect(GROCY_LABEL_TYPES).toEqual(["product", "stock_entry", "chore", "battery", "recipe"]);
    expect(grocyLabelKeys()).toEqual([
      "integrations.grocy.label.enabled",
      "integrations.grocy.label.printer",
      ...GROCY_LABEL_TYPES.flatMap((type) => [`integrations.grocy.label.${type}.content_type`, `integrations.grocy.label.${type}.printer`]),
    ]);
  });
});

describe("labelPrinterOptions", () => {
  const printers = [
    { slug: "desk", name: "Desk", backend: "ptouch", enabled: true },
    { slug: "office", name: "Office laser", backend: "ipp", enabled: true },
    { slug: "spare", name: "Spare", backend: "ptouch", enabled: false },
  ];

  it("offers the empty choice and the enabled tape printers only", () => {
    expect(labelPrinterOptions(printers, "", "First enabled tape printer", (slug) => slug)).toEqual([
      { id: "", label: "First enabled tape printer" },
      { id: "desk", label: "Desk" },
    ]);
  });

  it("shows a saved printer by its slug, not as unavailable, while the printers are not known", () => {
    expect(labelPrinterOptions(null, "desk", "Same as default", (slug) => `${slug} (not available)`)).toEqual([
      { id: "", label: "Same as default" },
      { id: "desk", label: "desk" },
    ]);
    expect(labelPrinterOptions(null, "", "Same as default", (slug) => slug)).toEqual([{ id: "", label: "Same as default" }]);
  });

  it("keeps a saved printer that cannot take labels now, marked as such", () => {
    expect(labelPrinterOptions(printers, "spare", "Same as default", (slug) => `${slug} (not available)`)).toEqual([
      { id: "", label: "Same as default" },
      { id: "desk", label: "Desk" },
      { id: "spare", label: "spare (not available)" },
    ]);
  });
});
