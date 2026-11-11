import { existsSync, readFileSync } from "node:fs";
import { isAbsolute, join, resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  EXTRA_RECORDS,
  checkLicences,
  expressionAllowed,
  extraPackagePaths,
  isUnacceptableLicence,
  loadPolicy,
  projectName,
  toCycloneDx,
  toLicenceList,
  type PluginPackage,
} from "./build";

const here = (path: string) => resolve(__dirname, path);
const policy = loadPolicy(here("../../../licence-policy.yml"));
const vectors = JSON.parse(readFileSync(here("../../../docs/licence-test-vectors.json"), "utf8")) as {
  expression: string;
  allowed: boolean;
}[];

const pkg = (over: Partial<PluginPackage> & Pick<PluginPackage, "name" | "version">): PluginPackage => ({
  license: "MIT",
  licenseText: "text",
  repository: null,
  ...over,
});

describe("expressionAllowed", () => {
  // The same file drives backend/tests/unit/scripts/test_licence_report.py: one grammar, two implementations.
  it.each(vectors)("test_vector_$expression", ({ expression, allowed }) => {
    expect(expressionAllowed(expression, policy.allowed)).toBe(allowed);
  });

  it("test_malformed_expressions_are_refused", () => {
    for (const bad of ["MIT AND", "(MIT", "MIT)", "MIT OR OR MIT", "WITH MIT", "MIT WITH", "MIT; rm -rf /", "MIT AND (", "()"]) {
      expect(expressionAllowed(bad, policy.allowed), bad).toBe(false);
    }
  });
});

describe("isUnacceptableLicence", () => {
  it("test_refuses_a_licence_outside_the_allow_list", () => {
    expect(isUnacceptableLicence("GPL-2.0-only", policy)).toBe(true);
    expect(isUnacceptableLicence("MIT", policy)).toBe(false);
  });

  it("test_exception_for_the_purl_wins", () => {
    const declared = "AFL-2.1 AND AFL-3.0 AND BSD-3-Clause";
    expect(isUnacceptableLicence(declared, policy)).toBe(true);
    expect(isUnacceptableLicence(declared, policy, "pkg:npm/json-schema@0.4.0")).toBe(false);
  });

  it("test_exception_does_not_cover_another_version", () => {
    expect(isUnacceptableLicence("AFL-2.1 AND AFL-3.0 AND BSD-3-Clause", policy, "pkg:npm/json-schema@0.4.1")).toBe(true);
  });

  it("test_exception_licence_is_judged_too", () => {
    const strict = { allowed: new Set(["MIT"]), exceptions: new Map([["pkg:npm/x@1.0.0", "GPL-2.0-only"]]) };
    expect(isUnacceptableLicence("MIT", strict, "pkg:npm/x@1.0.0")).toBe(true);
  });
});

describe("loadPolicy", () => {
  it("test_policy_reads_allow_list_and_exceptions_by_purl", () => {
    expect(policy.allowed.has("MIT")).toBe(true);
    expect(policy.allowed.has("GPL-2.0-only")).toBe(false);
    expect(policy.exceptions.get("pkg:npm/json-schema@0.4.0")).toBe("AFL-2.1 OR BSD-3-Clause");
  });
});

describe("projectName", () => {
  it("test_project_name_is_read_from_package_json", () => {
    const own = JSON.parse(readFileSync(here("../../package.json"), "utf8")) as { name: string };
    expect(projectName()).toBe(own.name);
  });
});

describe("toLicenceList", () => {
  it("test_list_has_exactly_the_five_keys_and_is_sorted", () => {
    const raw = [
      { ...pkg({ name: "b", version: "1.0.0", repository: "git+https://github.com/o/b.git" }), author: "x", source: "y" },
      pkg({ name: "A", version: "1.0.0" }),
      pkg({ name: "c", version: "1.0.0" }),
    ];
    const list = JSON.parse(toLicenceList(raw, [])) as Record<string, unknown>[];
    expect(list.map((r) => r.name)).toEqual(["A", "b", "c"]);
    for (const record of list) expect(Object.keys(record).sort()).toEqual(["license", "licenseText", "name", "repository", "version"]);
    expect(list[1]!.repository).toBe("https://github.com/o/b.git");
  });

  it("test_extra_records_are_merged_and_duplicates_dropped", () => {
    const list = JSON.parse(toLicenceList([pkg({ name: "react", version: "1.0.0" }), pkg({ name: "react", version: "1.0.0" })], EXTRA_RECORDS)) as {
      name: string;
    }[];
    expect(list.map((r) => r.name)).toEqual(["react", "zxing-cpp"]);
  });

  it("test_repository_is_only_ever_http_or_https_or_null", () => {
    const repo = (repository: string | null) => (JSON.parse(toLicenceList([pkg({ name: "p", version: "1.0.0", repository })], [])) as { repository: string | null }[])[0]!.repository;
    expect(repo("javascript:alert(1)")).toBeNull();
    expect(repo("data:text/html,<script>")).toBeNull();
    expect(repo("github:owner/repo")).toBeNull();
    expect(repo("git://github.com/o/r.git")).toBe("https://github.com/o/r.git");
    expect(repo("https://example.org/r")).toBe("https://example.org/r");
    expect(repo(null)).toBeNull();
    expect(repo("")).toBeNull();
  });

  it("test_missing_licence_text_becomes_null", () => {
    const list = JSON.parse(toLicenceList([{ ...pkg({ name: "p", version: "1.0.0" }), licenseText: undefined as unknown as null }], [])) as { licenseText: unknown }[];
    expect(list[0]!.licenseText).toBeNull();
  });

  it("test_scalar_packages_without_a_licence_file_get_the_scalar_mit_text", () => {
    const text = (record: PluginPackage) => (JSON.parse(toLicenceList([record], [])) as { licenseText: string | null }[])[0]!.licenseText;
    const scalar = readFileSync(here("../../licenses/scalar-api-reference-MIT.txt"), "utf8");
    expect(text(pkg({ name: "@scalar/schemas", version: "1.0.0", licenseText: null }))).toBe(scalar);
    expect(text(pkg({ name: "@scalar/schemas", version: "1.0.0", licenseText: "their own" }))).toBe("their own");
    // Only an MIT package of the Scalar repository may borrow the text; anything else stays honestly empty.
    expect(text(pkg({ name: "@scalar/schemas", version: "1.0.0", license: "Apache-2.0", licenseText: null }))).toBeNull();
    expect(text(pkg({ name: "@scalarish/x", version: "1.0.0", licenseText: null }))).toBeNull();
    expect(text(pkg({ name: "left-pad", version: "1.0.0", licenseText: null }))).toBeNull();
  });

  it("test_text_is_kept_verbatim", () => {
    const text = "<script>alert(1)</script>\nü";
    const list = JSON.parse(toLicenceList([pkg({ name: "p", version: "1.0.0", licenseText: text })], [])) as { licenseText: string }[];
    expect(list[0]!.licenseText).toBe(text);
  });
});

describe("EXTRA_RECORDS", () => {
  it("test_zxing_cpp_record_carries_its_apache_text", () => {
    expect(EXTRA_RECORDS).toHaveLength(1);
    const [zxing] = EXTRA_RECORDS;
    expect(zxing).toMatchObject({ name: "zxing-cpp", license: "Apache-2.0" });
    expect(zxing!.version).toMatch(/^\d+\.\d+\.\d+$/);
    expect(zxing!.licenseText).toContain("Apache License");
    expect(zxing!.licenseText).toContain("END OF TERMS AND CONDITIONS");
  });
});

describe("toCycloneDx", () => {
  const packages = [
    pkg({ name: "@tanstack/react-query", version: "5.105.3" }),
    pkg({ name: "react", version: "19.3.1" }),
    pkg({ name: "@scalar/api-reference", version: "1.77.0", license: "MIT" }),
  ];

  it("test_purl_of_a_scoped_package_escapes_the_at_sign", () => {
    const bom = JSON.parse(toCycloneDx(packages, [], "1.2.3", "app-web")) as { components: { purl: string }[] };
    expect(bom.components.map((c) => c.purl)).toContain("pkg:npm/%40tanstack/react-query@5.105.3");
    expect(bom.components.map((c) => c.purl)).toContain("pkg:npm/react@19.3.1");
  });

  it("test_document_shape_is_cyclonedx_1_6_without_serial_number_or_timestamp", () => {
    const bom = JSON.parse(toCycloneDx(packages, EXTRA_RECORDS, "1.2.3", "app-web")) as Record<string, unknown> & {
      metadata: Record<string, unknown>;
      components: Record<string, unknown>[];
    };
    expect(bom).toMatchObject({ bomFormat: "CycloneDX", specVersion: "1.6", version: 1 });
    expect(bom).not.toHaveProperty("serialNumber");
    expect(bom.metadata).not.toHaveProperty("timestamp");
    expect(bom.metadata.component).toEqual({ type: "application", name: "app-web", version: "1.2.3" });
    for (const component of bom.components) {
      expect(component.type).toBe("library");
      expect(component.licenses).toEqual([{ expression: expect.any(String) }]);
    }
  });

  it("test_zxing_cpp_is_a_github_purl", () => {
    const bom = JSON.parse(toCycloneDx([], EXTRA_RECORDS, "1.2.3", "app-web")) as { components: { purl: string }[] };
    expect(bom.components[0]!.purl).toBe(`pkg:github/zxing-cpp/zxing-cpp@${EXTRA_RECORDS[0]!.version}`);
  });

  it("test_components_are_sorted_by_purl_and_unique", () => {
    const bom = JSON.parse(toCycloneDx([...packages, packages[1]!], EXTRA_RECORDS, "1.2.3", "app-web")) as { components: { purl: string }[] };
    const purls = bom.components.map((c) => c.purl);
    expect(purls).toEqual([...purls].sort());
    expect(new Set(purls).size).toBe(purls.length);
  });

  it("test_two_calls_give_identical_strings", () => {
    const first = toCycloneDx(packages, EXTRA_RECORDS, "1.2.3", "app-web");
    expect(toCycloneDx([...packages].reverse(), EXTRA_RECORDS, "1.2.3", "app-web")).toBe(first);
    expect(toCycloneDx(packages, EXTRA_RECORDS, "1.2.3", "app-web")).toBe(first);
  });

  it("test_metadata_component_name_follows_the_argument", () => {
    const name = (n: string) => (JSON.parse(toCycloneDx(packages, [], "1.0.0", n)) as { metadata: { component: { name: string } } }).metadata.component.name;
    expect(name("one")).toBe("one");
    expect(name("two")).toBe("two");
  });
});

describe("extraPackagePaths", () => {
  it("test_paths_cover_the_code_the_bundler_does_not_see", { timeout: 60_000 }, async () => {
    const paths = await extraPackagePaths();
    const names = paths.map((p) => (JSON.parse(readFileSync(join(p, "package.json"), "utf8")) as { name: string }).name);
    for (const wanted of ["@scalar/api-reference", "zxing-wasm", "@fontsource/atkinson-hyperlegible", "@fontsource/atkinson-hyperlegible-mono", "workbox-core", "workbox-precaching", "workbox-routing", "workbox-strategies"]) {
      expect(names, wanted).toContain(wanted);
    }
    // The tree of Scalar's standalone bundle, not just its root.
    expect(paths.length).toBeGreaterThan(50);
    for (const p of paths) {
      expect(isAbsolute(p)).toBe(true);
      expect(existsSync(join(p, "package.json"))).toBe(true);
    }
    expect(new Set(paths).size).toBe(paths.length);
    // Development tools are not part of what ships.
    for (const tool of ["vite", "vitest", "typescript", "eslint", "rollup-license-plugin", "@playwright/test"]) expect(names).not.toContain(tool);
  });
});

describe("checkLicences", () => {
  const declared = "AFL-2.1 AND AFL-3.0 AND BSD-3-Clause";

  it("test_exception_applies_to_the_package_it_names", () => {
    // Without the purl the declared licence is refused; the exception for pkg:npm/json-schema@0.4.0 lets it pass.
    expect(() => checkLicences([pkg({ name: "json-schema", version: "0.4.0", license: declared })], [], policy)).not.toThrow();
  });

  it("test_exception_does_not_cover_another_version_or_name", () => {
    expect(() => checkLicences([pkg({ name: "json-schema", version: "0.4.1", license: declared })], [], policy)).toThrow(/json-schema@0\.4\.1/);
    expect(() => checkLicences([pkg({ name: "other", version: "0.4.0", license: declared })], [], policy)).toThrow(/other@0\.4\.0/);
  });

  it("test_scoped_package_exception_uses_the_escaped_purl", () => {
    const scoped = { allowed: new Set(["MIT"]), exceptions: new Map([["pkg:npm/%40a/b@1.0.0", "MIT"]]) };
    expect(() => checkLicences([pkg({ name: "@a/b", version: "1.0.0", license: "GPL-2.0-only" })], [], scoped)).not.toThrow();
  });

  it("test_names_every_offender", () => {
    const bad = [pkg({ name: "x", version: "1.0.0", license: "GPL-2.0-only" }), pkg({ name: "y", version: "2.0.0", license: "SSPL-1.0" })];
    expect(() => checkLicences(bad, [], policy)).toThrow(/x@1\.0\.0[\s\S]*y@2\.0\.0/);
  });

  it("test_allowed_packages_and_extra_records_pass", () => {
    expect(() => checkLicences([pkg({ name: "react", version: "19.3.1" })], EXTRA_RECORDS, policy)).not.toThrow();
  });
});
