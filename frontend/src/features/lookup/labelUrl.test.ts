import { describe, expect, it } from "vitest";
import { lookupIdFromQrPath, parseLabelUrl, resolveInput } from "./labelUrl";

describe("parseLabelUrl", () => {
  it.each([
    ["https://hub.example.invalid/asset/42", { app: "snipeit", id: "42" }],
    ["https://hub.example.invalid/loc/17", { app: "snipeit", id: "loc:17" }],
    ["https://hub.example.invalid/spool/5", { app: "spoolman", id: "5" }],
    ["https://hub.example.invalid/product/9", { app: "grocy", id: "9" }],
    ["http://192.0.2.7:8000/asset/HH-0042/", { app: "snipeit", id: "HH-0042" }],
    ["https://hub.example.invalid/hub/asset/42?x=1#top", { app: "snipeit", id: "42" }],
    ["/asset/42", { app: "snipeit", id: "42" }],
    ["  https://hub.example.invalid/asset/A%2F1  ", { app: "snipeit", id: "A/1" }],
  ])("%s", (raw, want) => {
    expect(parseLabelUrl(raw)).toEqual(want);
  });

  it.each(["", "42", "HH-0042", "loc:17", "asset/42", "https://hub.example.invalid/", "https://hub.example.invalid/asset/", "https://hub.example.invalid/assets/42", "https://hub.example.invalid/asset/42/extra", "javascript:alert(1)//asset/1", "ftp://hub.example.invalid/asset/42", "https://hub.example.invalid/asset/%E0%A4%A"])(
    "%j is not a label link",
    (raw) => {
      expect(parseLabelUrl(raw)).toBeNull();
    },
  );
});

describe("resolveInput", () => {
  it("a plain value stays in the app of the page", () => {
    expect(resolveInput("grocy", "  4001234567890 ")).toEqual({ app: "grocy", id: "4001234567890" });
  });
  it("a label link goes to the app printed on it, whatever page it was pasted on", () => {
    expect(resolveInput("grocy", "https://hub.example.invalid/spool/5")).toEqual({ app: "spoolman", id: "5" });
  });
  it("loc: is lower-cased so the server sees one spelling", () => {
    expect(resolveInput("snipeit", "LOC:17")).toEqual({ app: "snipeit", id: "loc:17" });
  });
  it("nothing to look up for blank input", () => {
    expect(resolveInput("snipeit", "   ")).toBeNull();
  });
});

describe("lookupIdFromQrPath", () => {
  it("only the /loc path carries the loc: prefix", () => {
    expect(lookupIdFromQrPath("loc", "5")).toBe("loc:5");
    expect(lookupIdFromQrPath("asset", "5")).toBe("5");
    expect(lookupIdFromQrPath("spool", "5")).toBe("5");
    expect(lookupIdFromQrPath("product", "5")).toBe("5");
  });
});
