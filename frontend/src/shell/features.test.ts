// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { describe, expect, it } from "vitest";
import type { IntegrationState } from "../features/integrations/api";
import { NAV_GROUPS, navGroups, SETTINGS_SECTIONS, visibleGroups } from "./features";

describe("navigation entries", () => {
  const all = { sheets: true, calibration: true, asn: true, kept: true };

  it("lists every entry when all features are on", () => {
    const names = visibleGroups((f) => all[f as keyof typeof all] ?? true, { admin: true }).flatMap((g) => g.entries.map((e) => e.id));
    expect(names).toEqual(NAV_GROUPS.flatMap((g) => g.entries.map((e) => e.id)));
  });

  it("drops entries and then empty groups", () => {
    const groups = visibleGroups(() => false, { admin: true });
    const ids = groups.flatMap((g) => g.entries.map((e) => e.id));
    expect(ids).toEqual(["overview", "printers", "jobs", "settings"]);
    expect(groups.map((g) => g.id)).toEqual(["main", "system"]);
  });

  it("an admin sees Settings", () => {
    const system = visibleGroups(() => true, { admin: true }).find((g) => g.id === "system");
    expect(system?.entries.map((e) => e.id)).toEqual(["settings"]);
  });

  it("a print session does not see Settings and the System group disappears", () => {
    const groups = visibleGroups(() => true, { admin: false });
    expect(groups.flatMap((g) => g.entries.map((e) => e.id))).not.toContain("settings");
    expect(groups.map((g) => g.id)).not.toContain("system");
  });

  it("navGroups keeps the integrations group when only integrations are configured", () => {
    const integrations: IntegrationState[] = [{ app: "grocy", configured: true }];
    const ids = navGroups({ isOn: () => false, admin: true, integrations }).map((g) => g.id);
    expect(ids).toContain("integrations");
    const none = navGroups({ isOn: () => false, admin: true, integrations: [] }).map((g) => g.id);
    expect(none).not.toContain("integrations");
  });

  it("SETTINGS_SECTIONS lists the six sections in the settings order", () => {
    expect(SETTINGS_SECTIONS.map((s) => [s.id, s.to])).toEqual([
      ["general", "/settings"],
      ["printers", "/settings/printers"],
      ["integrations", "/settings/integrations"],
      ["access", "/settings/access"],
      ["jobs", "/settings/jobs"],
      ["system", "/settings/system"],
    ]);
  });
});
