// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { describe, expect, it } from "vitest";
import { SHEET_TYPE } from "../test-api";
import { GROCY_LABEL_TYPES, grocyConfigBlock, grocyLabelChanges, grocyLabelKeys, grocyTargetIssues, labelPrinterOptions } from "./grocyLabel";

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
  it("lists the switch, the default target and a layout and target per type", () => {
    expect(GROCY_LABEL_TYPES).toEqual(["product", "stock_entry", "chore", "battery", "recipe"]);
    expect(grocyLabelKeys()).toEqual([
      "integrations.grocy.label.enabled",
      "integrations.grocy.label.printer",
      "integrations.grocy.label.sheet_type",
      ...GROCY_LABEL_TYPES.flatMap((type) => [
        `integrations.grocy.label.${type}.content_type`,
        `integrations.grocy.label.${type}.printer`,
        `integrations.grocy.label.${type}.sheet_type`,
      ]),
    ]);
  });
});

describe("labelPrinterOptions", () => {
  const printers = [
    { slug: "desk", name: "Desk", backend: "ptouch", enabled: true },
    { slug: "office", name: "Office laser", backend: "ipp", enabled: true },
    { slug: "spare", name: "Spare", backend: "ptouch", enabled: false },
  ];

  const groups = { tape: "Tape printers", page: "Page printers" };

  it("offers the empty choice, then the enabled tape and page printers in their groups", () => {
    expect(labelPrinterOptions(printers, "", "First enabled tape printer", (slug) => slug, groups)).toEqual([
      { id: "", label: "First enabled tape printer" },
      { id: "desk", label: "Desk", section: "Tape printers" },
      { id: "office", label: "Office laser", section: "Page printers" },
    ]);
  });

  it("shows a saved printer by its slug, not as unavailable, while the printers are not known", () => {
    expect(labelPrinterOptions(null, "desk", "Same as default", (slug) => `${slug} (not available)`, groups)).toEqual([
      { id: "", label: "Same as default" },
      { id: "desk", label: "desk" },
    ]);
    expect(labelPrinterOptions(null, "", "Same as default", (slug) => slug, groups)).toEqual([{ id: "", label: "Same as default" }]);
  });

  it("keeps a saved printer that cannot take labels now, marked as such", () => {
    expect(labelPrinterOptions(printers, "spare", "Same as default", (slug) => `${slug} (not available)`, groups)).toEqual([
      { id: "", label: "Same as default" },
      { id: "desk", label: "Desk", section: "Tape printers" },
      { id: "office", label: "Office laser", section: "Page printers" },
      { id: "spare", label: "spare (not available)" },
    ]);
  });
});

describe("grocyTargetIssues", () => {
  const printers = [
    { slug: "desk", name: "Desk", backend: "ptouch", enabled: true },
    { slug: "office", name: "Office laser", backend: "ipp", enabled: true },
  ];
  const archived = { ...SHEET_TYPE, key: "OLD", archived_at: "2026-11-02T08:00:00Z" };
  const types = [SHEET_TYPE, archived];
  const P = "integrations.grocy.label.printer";
  const S = "integrations.grocy.label.sheet_type";
  const BP = "integrations.grocy.label.battery.printer";
  const BS = "integrations.grocy.label.battery.sheet_type";

  it("needs a sheet type for a page printer", () => {
    expect(grocyTargetIssues({ [P]: "office", [S]: "" }, printers, types)).toEqual({ default: "sheet_type_required" });
    expect(grocyTargetIssues({ [BP]: "office", [BS]: "" }, printers, types)).toEqual({ battery: "sheet_type_required" });
  });

  it("flags an archived or unknown sheet type", () => {
    expect(grocyTargetIssues({ [P]: "office", [S]: "OLD" }, printers, types)).toEqual({ default: "sheet_type_unavailable" });
    expect(grocyTargetIssues({ [BP]: "office", [BS]: "GONE" }, printers, types)).toEqual({ battery: "sheet_type_unavailable" });
  });

  it("has nothing to say about a tape printer, the default target or a usable type", () => {
    expect(grocyTargetIssues({ [P]: "desk", [S]: "" }, printers, types)).toEqual({});
    expect(grocyTargetIssues({ [P]: "", [BP]: "", [BS]: "GONE" }, printers, types)).toEqual({});
    expect(grocyTargetIssues({ [P]: "office", [S]: SHEET_TYPE.key }, printers, types)).toEqual({});
  });

  it("does not guess while the types are not known", () => {
    expect(grocyTargetIssues({ [P]: "office", [S]: "GONE" }, printers, null)).toEqual({});
    expect(grocyTargetIssues({ [P]: "office", [S]: "" }, printers, null)).toEqual({ default: "sheet_type_required" });
  });
});

describe("grocyLabelChanges", () => {
  const printers = [
    { slug: "desk", name: "Desk", backend: "ptouch", enabled: true },
    { slug: "office", name: "Office laser", backend: "ipp", enabled: true },
  ];

  it("clears the sheet type when a target goes to a tape printer or the default", () => {
    expect(grocyLabelChanges("battery", "desk", printers)).toEqual({
      "integrations.grocy.label.battery.printer": "desk",
      "integrations.grocy.label.battery.sheet_type": "",
    });
    expect(grocyLabelChanges("battery", "", printers)).toEqual({
      "integrations.grocy.label.battery.printer": "",
      "integrations.grocy.label.battery.sheet_type": "",
    });
    expect(grocyLabelChanges("default", "", printers)).toEqual({
      "integrations.grocy.label.printer": "",
      "integrations.grocy.label.sheet_type": "",
    });
  });

  it("keeps the sheet type when a target goes to a page printer", () => {
    expect(grocyLabelChanges("default", "office", printers)).toEqual({ "integrations.grocy.label.printer": "office" });
  });
});
