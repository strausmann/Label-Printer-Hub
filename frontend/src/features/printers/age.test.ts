import { describe, expect, it } from "vitest";
import { formatAge } from "./age";

describe("formatAge", () => {
  // 12349795 s = 142.9 days: floored to 142 (the plan text said 143, which rounds).
  it("names the largest whole unit, floored", () => {
    expect(formatAge(12349795, "en")).toBe("142 days ago");
    expect(formatAge(12349795, "de")).toBe("vor 142 Tagen");
    expect(formatAge(59, "en")).toBe("59 seconds ago");
    expect(formatAge(7200, "de")).toBe("vor 2 Stunden");
  });
  it("floors at the unit boundaries", () => {
    expect(formatAge(60, "en")).toBe("1 minute ago");
    expect(formatAge(119, "en")).toBe("1 minute ago");
    expect(formatAge(86_399, "en")).toBe("23 hours ago");
  });
  it("never says a negative or non-finite age", () => {
    expect(formatAge(-5, "en")).toBe("0 seconds ago");
    expect(formatAge(Number.NaN, "en")).toBe("0 seconds ago");
  });
});
