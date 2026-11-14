import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { parse } from "yaml";
import { GEOMETRY_L4736, SHEET_TYPE } from "../test-api";
import {
  browserLabel,
  buildFeedbackUrl,
  FEEDBACK_BASE,
  FEEDBACK_FIELD_IDS,
  MAX_URL,
  type FeedbackInput,
} from "./feedbackLink";

const TEMPLATE = resolve(import.meta.dirname, "../../../../.github/ISSUE_TEMPLATE/sheet-type-feedback.yml");
const VERSION = {
  version: 2,
  change_note: "Pitch measured again",
  created_at: "2026-11-01T08:00:00Z",
  geometry: GEOMETRY_L4736,
  geometry_hash: "abc",
  sheets: 3,
};

const input = (over: Partial<FeedbackInput> = {}): FeedbackInput => ({
  kind: "wrong",
  sheetType: {
    ...SHEET_TYPE,
    source_name: "Vendor data sheet",
    source_url: "https://vendor.example/ds.pdf",
    source_url_shipped: true,
  },
  version: VERSION,
  hubVersion: "1.5.0",
  scheme: "https",
  ...over,
});

const params = (url: string) => new URL(url).searchParams;
const present = (url: string) => [...params(url).keys()];

describe("the issue form and the builder agree", () => {
  it("yaml ids equal builder ids", () => {
    const doc = parse(readFileSync(TEMPLATE, "utf8")) as { body: { id?: string }[] };
    const ids = doc.body.map((b) => b.id).filter((id): id is string => Boolean(id));
    expect(ids).toEqual([...FEEDBACK_FIELD_IDS]);
  });

  it("is a valid GitHub issue form", () => {
    const doc = parse(readFileSync(TEMPLATE, "utf8")) as {
      name: string;
      description: string;
      body: { type: string; id?: string; attributes: Record<string, unknown> }[];
    };
    expect(doc.name).toBeTruthy();
    expect(doc.description).toBeTruthy();
    expect(doc.body.length).toBeGreaterThan(0);
    for (const element of doc.body) {
      expect(["markdown", "textarea", "input", "dropdown", "checkboxes"]).toContain(element.type);
      expect(element.attributes).toBeTypeOf("object");
      if (element.type !== "markdown") expect(element.id).toMatch(/^[a-z_]+$/);
    }
  });

  it("only offers values the dropdowns of the form contain", () => {
    const doc = parse(readFileSync(TEMPLATE, "utf8")) as {
      body: { id?: string; type: string; attributes: { options?: string[] } }[];
    };
    const options = (id: string) => doc.body.find((b) => b.id === id)!.attributes.options!;
    const wrong = params(buildFeedbackUrl(input()));
    const confirmed = params(buildFeedbackUrl(input({ kind: "confirmed" })));
    expect(options("kind")).toContain(wrong.get("kind"));
    expect(options("kind")).toContain(confirmed.get("kind"));
    expect(options("allow_qr")).toContain(wrong.get("allow_qr"));
    expect(options("verified")).toContain(wrong.get("verified"));
    expect(options("scheme")).toContain(wrong.get("scheme"));
    const printer = params(
      buildFeedbackUrl(input({ printer: { model: "PT-P750W", tray: "Tray 1", calibration: "calibrated" } })),
    );
    expect(options("calibration")).toContain(printer.get("calibration"));
  });
});

describe("buildFeedbackUrl", () => {
  it("starts at the template, with the title and labels of each kind", () => {
    const wrong = buildFeedbackUrl(input());
    expect(wrong.startsWith(`${FEEDBACK_BASE}&`)).toBe(true);
    expect(FEEDBACK_BASE).toBe("https://github.com/strausmann/labelyard/issues/new?template=sheet-type-feedback.yml");
    expect(params(wrong).get("title")).toBe("[sheet type] L4736REV v2: dimensions wrong");
    expect(params(wrong).get("labels")).toBe("area:sheets,type:bug");
    const ok = buildFeedbackUrl(input({ kind: "confirmed" }));
    expect(params(ok).get("title")).toBe("[sheet type] L4736REV v2: dimensions confirmed");
    expect(params(ok).get("labels")).toBe("area:sheets,type:feedback");
  });

  it("geometry has every stored number with units", () => {
    const geometry = params(buildFeedbackUrl(input())).get("geometry")!;
    const lines = geometry.split("\n");
    const g = GEOMETRY_L4736;
    expect(lines).toContain(`label_w: ${g.label_w} mm`);
    expect(lines).toContain(`label_h: ${g.label_h} mm`);
    expect(lines).toContain(`pitch_x: ${g.pitch_x} mm`);
    expect(lines).toContain(`pitch_y: ${g.pitch_y} mm`);
    expect(lines).toContain(`margin_top: ${g.margin_top} mm`);
    expect(lines).toContain(`margin_left: ${g.margin_left} mm`);
    expect(lines).toContain(`cols: ${g.cols}`);
    expect(lines).toContain(`rows: ${g.rows}`);
    expect(lines).toContain(`page_size: ${g.page_size}`);
    expect(lines).toContain(`shape: ${g.shape}`);
    // Counts carry no unit, and a number the version does not store is not listed.
    expect(geometry).not.toMatch(/cols: \d+ mm/);
    expect(geometry).not.toContain("null");
    const round = params(
      buildFeedbackUrl(
        input({ version: { ...VERSION, geometry: { ...g, corner_radius: 2.5, page_w: 210, page_h: 297.5 } } }),
      ),
    ).get("geometry")!;
    expect(round).toContain("corner_radius: 2.5 mm");
    expect(round).toContain("page_w: 210 mm");
    expect(round).toContain("page_h: 297.5 mm");
  });

  it("encodes umlauts, &, # and newlines", () => {
    const tricky = {
      ...SHEET_TYPE,
      vendor: "Müller & Söhne #1\nZweite Zeile",
      product_codes: ["Ä-1", "A&B", "C#3"],
    };
    const url = buildFeedbackUrl(input({ sheetType: tricky }));
    expect(url).not.toContain("\n");
    expect(url).not.toMatch(/#/);
    const read = params(url);
    expect(read.get("vendor")).toBe("Müller & Söhne #1\nZweite Zeile");
    expect(read.get("product_codes")).toBe("Ä-1\nA&B\nC#3");
  });

  it("pre-fills everything but the observation and the privacy tick", () => {
    const keys = present(
      buildFeedbackUrl(input({ printer: { model: "PT-P750W", tray: "Tray 1", calibration: "uncalibrated" }, browser: "Firefox 140" })),
    );
    expect(keys).not.toContain("observed");
    expect(keys).not.toContain("privacy_check");
    for (const id of FEEDBACK_FIELD_IDS.filter((id) => id !== "observed" && id !== "privacy_check")) {
      expect(keys).toContain(id);
    }
  });

  it("names the source, and its URL only while it is the one shipped with the hub", () => {
    const seed = params(buildFeedbackUrl(input())).get("provenance")!;
    expect(seed).toContain("Vendor data sheet");
    expect(seed).toContain("https://vendor.example/ds.pdf");
    const intranet = "http://wiki.intranet.local/labels";
    for (const origin of ["custom", "imported"] as const) {
      const url = buildFeedbackUrl(
        input({ sheetType: { ...SHEET_TYPE, origin, source_name: "Our wiki", source_url: intranet } }),
      );
      expect(decodeURIComponent(url)).not.toContain("intranet");
      expect(params(url).get("provenance")).toContain("Our wiki");
    }
  });

  it("omits the URL of a seed type whose URL an admin edited", () => {
    const intranet = "http://wiki.intranet.local/labels";
    const url = buildFeedbackUrl(
      input({
        sheetType: { ...SHEET_TYPE, origin: "seed", source_name: "Vendor data sheet", source_url: intranet, source_url_shipped: false },
      }),
    );
    expect(decodeURIComponent(url)).not.toContain("intranet");
    expect(params(url).get("provenance")).toBe("Vendor data sheet");
  });

  it("carries no host, uri or key", () => {
    // A page state whose neighbours must never travel. It is spread into the very objects the builder
    // receives (sheet type, version, geometry), so a builder that serialises any of them wholesale leaks.
    const page = {
      location: { host: "hub.corp.internal:8443", href: "https://hub.corp.internal:8443/sheets/archive" },
      printer: { uri: "ipp://192.0.2.7:631/ipp/print", serial: "BRN-SERIAL-123", api_key: "lph_secret_key_value" },
      integration: { url: "https://snipe.corp.internal/api" },
      user: "alice",
      sheet: { code: "L4736-0001" },
    };
    const url = buildFeedbackUrl(
      input({
        sheetType: {
          ...SHEET_TYPE,
          ...page,
          origin: "custom",
          source_name: "Our printer",
          source_url: page.printer.uri,
          notes: page.location.host,
          description: page.printer.api_key,
        },
        version: { ...VERSION, ...page, geometry: { ...GEOMETRY_L4736, ...page } },
        printer: { model: "PT-P750W", tray: "Tray 1", calibration: "calibrated" },
      }),
    );
    const text = decodeURIComponent(url);
    for (const secret of [
      page.location.host,
      page.location.href,
      page.printer.uri,
      page.printer.serial,
      page.printer.api_key,
      page.integration.url,
      "alice",
      page.sheet.code,
    ]) {
      expect(text).not.toContain(secret);
    }
    // The page state really did reach the input, and the legitimate fields are still there.
    expect(params(url).get("type_key")).toBe("L4736REV");
    expect(params(url).get("provenance")).toBe("Our printer");
    // The only address in the URL is the relative export path, which has no host.
    const geometryOnly = params(buildFeedbackUrl(input())).get("geometry")!;
    expect(geometryOnly).not.toContain("http");
  });

  it("ignores everything on the sheet type that is not a named field", () => {
    const extra = { ...SHEET_TYPE, internal_note: "hub.corp.internal", created_at: "2026-11-01T08:00:00Z" };
    const text = decodeURIComponent(buildFeedbackUrl(input({ sheetType: extra })));
    expect(text).not.toContain("hub.corp.internal");
    expect(text).not.toContain("2026-11-01");
    expect(text).not.toContain("notes");
  });
});

describe("browserLabel", () => {
  it.each([
    ["Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0", "Firefox 140"],
    ["Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0", "Edge 130"],
    ["Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 Chrome/130.0.0.0 Safari/537.36", "Chrome 130"],
    ["Mozilla/5.0 (iPhone; CPU iPhone OS 18_0) AppleWebKit/605 Version/18.0 Mobile/15E148 Safari/604.1", "Safari 18"],
  ])("reduces %s to family and major version", (ua, label) => {
    expect(browserLabel(ua)).toBe(label);
  });

  it("says nothing for an agent it does not know", () => {
    expect(browserLabel("curl/8.0")).toBeUndefined();
  });
});

describe("degrading to fit", () => {
  const worst = (ballast: number): FeedbackInput =>
    input({
      sheetType: {
        ...SHEET_TYPE,
        vendor: "V".repeat(200),
        source_name: "S".repeat(200),
        source_url: `https://vendor.example/${"p".repeat(300)}`,
        source_url_shipped: true,
        // Encoded umlauts cost six bytes each: `ballast` characters spread over at most 50 codes of 40.
        product_codes: Array.from({ length: Math.ceil(ballast / 40) }, (_, i) =>
          "\u00c4".repeat(Math.min(40, ballast - i * 40)),
        ),
      },
      version: { ...VERSION, change_note: "N".repeat(500) },
      browser: "B".repeat(100),
      printer: { model: "M".repeat(100), tray: "T".repeat(100), calibration: "calibrated" },
    });

  /** How many of the documented steps the builder had to take, read off the URL. */
  function stage(url: string): number {
    const p = params(url);
    if (p.get("geometry")?.startsWith("See the export")) return 5;
    if (!p.get("provenance")?.includes("https://")) return 4;
    if (!p.has("version_note")) return 3;
    if (!p.has("printer_model")) return 2;
    if (!p.has("browser")) return 1;
    return 0;
  }

  const sweep = Array.from({ length: 101 }, (_, i) => i * 20).map((ballast) => buildFeedbackUrl(worst(ballast)));

  it("degrades in the documented order under 8000", () => {
    const stages = sweep.map(stage);
    // More ballast never brings a field back, and every step of the order is visited.
    expect(stages).toEqual([...stages].sort((a, b) => a - b));
    expect([...new Set(stages)]).toEqual([0, 1, 2, 3, 4, 5]);
    for (const url of sweep) expect(url.length).toBeLessThanOrEqual(MAX_URL);
  });

  it.each([
    [1, ["browser"], ["printer_model", "tray", "calibration", "version_note"]],
    [2, ["browser", "printer_model", "tray", "calibration"], ["version_note"]],
    [3, ["browser", "printer_model", "tray", "calibration", "version_note"], []],
  ])("at step %i exactly the documented fields are gone", (step, gone, kept) => {
    const url = sweep.find((u) => stage(u) === step)!;
    for (const key of gone) expect(present(url)).not.toContain(key);
    for (const key of kept) expect(present(url)).toContain(key);
    expect(params(url).get("provenance")).toContain("https://");
  });

  it("keeps the source name when the URL goes, and replaces geometry last", () => {
    const four = params(sweep.find((u) => stage(u) === 4)!);
    expect(four.get("provenance")).toContain("S".repeat(200));
    expect(four.get("geometry")).toContain("label_w:");
    const five = params(sweep.find((u) => stage(u) === 5)!);
    expect(five.get("geometry")).toBe("See the export: /api/v1/sheet-types/L4736REV/export (paste it here)");
    expect(five.get("provenance")).toContain("S".repeat(200));
  });

  it("stays under the limit with the worst values the server accepts", () => {
    const codes = Array.from({ length: 50 }, (_, i) => `${String(i).padStart(2, "0")}${"Ö".repeat(38)}`);
    const url = buildFeedbackUrl(
      input({
        sheetType: {
          ...SHEET_TYPE,
          key: "k".repeat(64),
          vendor: "\u00dc".repeat(200),
          product_codes: codes,
          source_name: "\u00c4".repeat(200),
          source_url: `https://example.invalid/${"\u00df".repeat(400)}`,
        },
        version: { ...VERSION, change_note: "\u00fc".repeat(500) },
        browser: "B".repeat(100),
        printer: { model: "M".repeat(100), tray: "T".repeat(100), calibration: "calibrated" },
      }),
    );
    expect(url.length).toBeLessThanOrEqual(MAX_URL);
    // The key and the version always survive: without them the issue says nothing.
    expect(params(url).get("type_key")).toBe("k".repeat(64));
    expect(params(url).get("type_version")).toBe("2");
    // The codes were cut honestly: the first ones are kept, in order, and the last line counts what is missing.
    const lines = params(url).get("product_codes")!.split("\n");
    const last = lines.pop()!;
    const missing = /^… and (\d+) more \(see the export\)$/.exec(last);
    expect(missing).not.toBeNull();
    expect(lines).toEqual(codes.slice(0, lines.length));
    expect(Number(missing![1])).toBe(codes.length - lines.length);
    expect(lines.length).toBeGreaterThan(0);
    expect(lines.length).toBeLessThan(codes.length);
    // The export pointer is already in place: the cut codes can be found there.
    expect(params(url).get("geometry")).toContain("/api/v1/sheet-types/");
  });
});
