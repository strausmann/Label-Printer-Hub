import { describe, expect, it } from "vitest";
import { baseUrlOf } from "./baseUrl";

describe("baseUrlOf", () => {
  it.each([
    ["snipeit", "https://assets.example.invalid/hardware/7", "https://assets.example.invalid"],
    ["snipeit", "https://assets.example.invalid/locations/17", "https://assets.example.invalid"],
    ["snipeit", "https://example.invalid/snipe/hardware/7", "https://example.invalid/snipe"],
    ["grocy", "http://192.0.2.5:9283/product/118", "http://192.0.2.5:9283"],
    ["spoolman", "https://spools.example.invalid/spool/show/5", "https://spools.example.invalid"],
  ] as const)("%s %s", (app, link, want) => {
    expect(baseUrlOf(app, link)).toBe(want);
  });

  it.each([
    ["snipeit", "https://assets.example.invalid/snipeit/42"],
    ["grocy", "https://assets.example.invalid/hardware/7"],
    ["spoolman", "not a url"],
  ] as const)("%s %s has no known base", (app, link) => {
    expect(baseUrlOf(app, link)).toBeNull();
  });
});
