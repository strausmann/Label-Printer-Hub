import { describe, expect, it } from "vitest";
import { queryString } from "./queryString";

describe("queryString", () => {
  it("leaves out undefined, null and empty values but keeps false and 0", () => {
    expect(queryString({ a: "x", b: undefined, c: null, d: "", e: false, f: 0, g: 1.5 })).toBe("?a=x&e=false&f=0&g=1.5");
  });
  it("is empty when nothing is set", () => {
    expect(queryString({ a: undefined })).toBe("");
  });
  it("encodes values", () => {
    expect(queryString({ q: "a b&c" })).toBe("?q=a+b%26c");
  });
});
