import { describe, expect, it } from "vitest";
import { NAV_GROUPS, visibleGroups } from "./features";

describe("navigation entries", () => {
  const all = { sheets: true, calibration: true, asn: true, kept: true };

  it("lists every entry when all features are on", () => {
    const names = visibleGroups((f) => all[f as keyof typeof all] ?? true).flatMap((g) => g.entries.map((e) => e.id));
    expect(names).toEqual(NAV_GROUPS.flatMap((g) => g.entries.map((e) => e.id)));
  });

  it("drops entries and then empty groups", () => {
    const groups = visibleGroups(() => false);
    const ids = groups.flatMap((g) => g.entries.map((e) => e.id));
    expect(ids).toEqual(["overview", "printers", "jobs", "settings"]);
    expect(groups.map((g) => g.id)).toEqual(["main", "system"]);
  });
});
