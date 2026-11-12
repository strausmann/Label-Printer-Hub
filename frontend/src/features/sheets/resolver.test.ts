import { describe, expect, it } from "vitest";
import { parseSheetCode, sheetResolver } from "./resolver";

describe("parseSheetCode", () => {
  it.each([
    ["https://hub.example.invalid/sheet/L4736-0002", "L4736-0002"],
    ["http://192.0.2.7:8000/sheet/L4736-0002/", "L4736-0002"],
    ["https://hub.example.invalid/hub/sheet/L4736-0002", "L4736-0002"],
    ["https://hub.example.invalid/sheet/L4736-0002?x=1#top", "L4736-0002"],
    ["/sheet/L4736-0002", "L4736-0002"],
    ["sheet:L4736-0002", "L4736-0002"],
    ["  sheet:L4736-0002 \n", "L4736-0002"],
    ["SHEET:L4736-0002", "L4736-0002"],
    ["sheet:A1-1234567890", "A1-1234567890"],
    ["sheet:A1-123456789012345678901", "A1-123456789012345678901"],
  ])("%s -> %s", (text, code) => {
    expect(parseSheetCode(text)).toBe(code);
  });

  it.each([
    ["lowercase code", "https://hub.example.invalid/sheet/l4736-0002"],
    ["lowercase short form", "sheet:l4736-0002"],
    ["too few digits", "sheet:L4736-2"],
    ["three digits", "sheet:L4736-002"],
    ["two digits (264-08)", "sheet:L4736-02"],
    ["two digits, bare (264-08)", "L4736-02"],
    ["two digits, in a link (264-08)", "https://hub.example.invalid/sheet/L4736-02"],
    ["no prefix letter", "sheet:4736-0002"],
    ["one-character prefix", "sheet:L-0002"],
    ["prefix of 11 characters", "sheet:ABCDEFGHIJK-0002"],
    ["longer than 24 characters", "sheet:A1-1234567890123456789012"],
    ["another path", "https://hub.example.invalid/asset/L4736-0002"],
    ["the archive path", "https://hub.example.invalid/sheets/L4736-0002"],
    ["a sub-path behind the code", "https://hub.example.invalid/sheet/L4736-0002/cells"],
    ["no code", "https://hub.example.invalid/sheet/"],
    ["bare code", "L4736-0002"],
    ["javascript scheme", "javascript:alert(1)//sheet/L4736-0002"],
    ["file scheme", "file:///sheet/L4736-0002"],
    ["encoded slash", "https://hub.example.invalid/sheet/L4736%2F0002"],
    ["broken escape", "https://hub.example.invalid/sheet/%E0%A4%A"],
    ["empty", ""],
  ])("%s -> null", (_name, text) => {
    expect(parseSheetCode(text)).toBeNull();
  });
});

describe("sheetResolver", () => {
  it("claims a sheet code and leads to /sheet/<code>", () => {
    const hit = { format: "qr_code", text: "https://hub.example.invalid/sheet/L4736-0002" };
    expect(sheetResolver.id).toBe("sheet");
    expect(sheetResolver.match(hit)).toBe(true);
    expect(sheetResolver.resolve(hit)).toBe("/sheet/L4736-0002");
  });

  it("does not claim other codes", () => {
    expect(sheetResolver.match({ format: "qr_code", text: "https://hub.example.invalid/asset/42" })).toBe(false);
  });
});
