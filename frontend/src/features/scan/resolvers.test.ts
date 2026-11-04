import { afterEach, describe, expect, it } from "vitest";
import { registerScanResolver, resolveScan } from "./resolvers";

const qr = (text: string) => ({ format: "qr_code", text });
const cleanups: Array<() => void> = [];
afterEach(() => {
  while (cleanups.length) cleanups.pop()!();
});

describe("resolvers", () => {
  it("printed asset URL from any host resolves to /asset/<id>", () => {
    expect(resolveScan(qr("https://hub.example.invalid/asset/42"))?.route).toBe("/asset/42");
    expect(resolveScan(qr("http://192.0.2.7:8000/asset/42/"))?.route).toBe("/asset/42");
    expect(resolveScan(qr("https://other.example.invalid/hub/asset/42?x=1"))?.route).toBe("/asset/42");
  });

  it.each([
    ["https://hub.example.invalid/loc/17", "/loc/17"],
    ["https://hub.example.invalid/spool/5", "/spool/5"],
    ["https://hub.example.invalid/product/9", "/product/9"],
    ["https://hub.example.invalid/asset/A%2F1", "/asset/A%2F1"],
  ])("%s", (text, route) => {
    expect(resolveScan(qr(text))?.route).toBe(route);
  });

  it("a bare job UUID resolves to /jobs/<id>, in lower case", () => {
    expect(resolveScan({ format: "code_128", text: "0F3A9C1E-7B2D-4E5F-8A6B-1C2D3E4F5A6B" })?.route).toBe(
      "/jobs/0f3a9c1e-7b2d-4e5f-8a6b-1c2d3e4f5a6b",
    );
  });

  it("unknown code returns null", () => {
    expect(resolveScan(qr("WIFI:S:guest;T:WPA;P:fake;;"))).toBeNull();
    expect(resolveScan(qr("https://hub.example.invalid/"))).toBeNull();
    expect(resolveScan(qr("https://hub.example.invalid/assets/42"))).toBeNull();
    expect(resolveScan(qr("0f3a9c1e-7b2d-4e5f-8a6b"))).toBeNull();
    expect(resolveScan(qr(""))).toBeNull();
  });

  it("a later module can register its own resolver and is asked after the foundation's", () => {
    cleanups.push(
      registerScanResolver({
        id: "t-sheet",
        match: (hit) => hit.text.startsWith("SHEET-"),
        resolve: (hit) => `/sheets/${hit.text.slice(6)}`,
      }),
    );
    expect(resolveScan(qr("SHEET-7"))).toEqual({ resolverId: "t-sheet", route: "/sheets/7" });
    cleanups.pop()!();
    expect(resolveScan(qr("SHEET-7"))).toBeNull();
  });
});
