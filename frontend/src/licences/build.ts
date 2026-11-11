// Build-time only: the licence check, the licence list and the CycloneDX document of the web bundle.
// Nothing here is imported by the app; `vite.config.ts` feeds it to `rollup-license-plugin`.
import { existsSync, readFileSync, realpathSync } from "node:fs";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

// Paths come from `node:path`, not `new URL(...)`: under vitest's jsdom the global URL resolves a file: base to http://localhost.
const frontendDir = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const readText = (path: string) => readFileSync(resolve(frontendDir, path), "utf8");

/** One package of the list: the five keys that `backend.json` and `frontend.json` share. */
export type PluginPackage = {
  name: string;
  version: string;
  license: string;
  licenseText: string | null;
  repository: string | null;
};

export type Policy = { allowed: ReadonlySet<string>; exceptions: ReadonlyMap<string, string> };

/** Read `licence-policy.yml` (a JSON file, shared with the dependency review and the backend check). */
export function loadPolicy(path: string): Policy {
  const data: unknown = JSON.parse(readFileSync(path, "utf8"));
  if (typeof data !== "object" || data === null) throw new Error(`${path}: the policy must be an object`);
  const { "allow-licenses": licences, "x-licence-exceptions": raw = [] } = data as Record<string, unknown>;
  if (!Array.isArray(licences) || licences.length === 0 || !licences.every((l) => typeof l === "string")) {
    throw new Error(`${path}: allow-licenses must be a non-empty list of strings`);
  }
  if (!Array.isArray(raw)) throw new Error(`${path}: x-licence-exceptions must be a list`);
  const exceptions = new Map<string, string>();
  for (const entry of raw as Record<string, unknown>[]) {
    if (typeof entry?.purl !== "string" || typeof entry.licence !== "string" || !entry.purl.trim() || !entry.licence.trim()) {
      throw new Error(`${path}: an exception needs a purl and a licence: ${JSON.stringify(entry)}`);
    }
    exceptions.set(entry.purl, entry.licence);
  }
  return { allowed: new Set(licences), exceptions };
}

// ---- SPDX expressions: the grammar of backend/scripts/licence_report.py `expression_allowed` ----------

const TOKEN = /\(|\)|[A-Za-z0-9][A-Za-z0-9.+:-]*/g;
const KEYWORDS = new Set(["(", ")", "AND", "OR", "WITH"]);

class Parser {
  private pos = 0;
  constructor(
    private readonly tokens: readonly string[],
    private readonly allowed: ReadonlySet<string>,
  ) {}

  private peek(): string | undefined {
    return this.tokens[this.pos];
  }

  private next(): string {
    const token = this.tokens[this.pos];
    if (token === undefined) throw new Error("unexpected end");
    this.pos += 1;
    return token;
  }

  parse(): boolean {
    const result = this.or();
    if (this.peek() !== undefined) throw new Error("trailing tokens");
    return result;
  }

  private or(): boolean {
    let result = this.and();
    while (this.peek() === "OR") {
      this.next();
      const right = this.and(); // always parse the right side, it may be malformed
      result = result || right;
    }
    return result;
  }

  private and(): boolean {
    let result = this.atom();
    while (this.peek() === "AND") {
      this.next();
      const right = this.atom();
      result = result && right;
    }
    return result;
  }

  private atom(): boolean {
    const token = this.peek();
    if (token === undefined) throw new Error("unexpected end");
    if (token === "(") {
      this.next();
      const result = this.or();
      if (this.peek() !== ")") throw new Error("missing )");
      this.next();
      return result;
    }
    if (KEYWORDS.has(token)) throw new Error(`unexpected ${token}`);
    this.next();
    const result = this.allowed.has(token);
    if (this.peek() === "WITH") {
      // The exception is judged by the licence it modifies.
      this.next();
      const exception = this.peek();
      if (exception === undefined || KEYWORDS.has(exception)) throw new Error("WITH needs an exception id");
      this.next();
    }
    return result;
  }
}

/**
 * Whether an SPDX expression is covered by the allow list: `OR` means any branch, `AND` all branches,
 * `X WITH Y` is judged by `X`. An empty or unparseable expression is not allowed. The same grammar as the
 * Python `expression_allowed`; `docs/licence-test-vectors.json` holds the cases both must agree on.
 */
export function expressionAllowed(expr: string, allowed: ReadonlySet<string>): boolean {
  const stripped = expr.trim();
  if (!stripped) return false;
  const tokens = stripped.match(TOKEN) ?? [];
  if (tokens.join("") !== stripped.replace(/\s+/g, "")) return false; // characters outside the SPDX grammar
  try {
    return new Parser(tokens, allowed).parse();
  } catch {
    return false;
  }
}

/** Whether the build must fail for a package: the exception for its purl wins, else the allow list decides. */
export function isUnacceptableLicence(id: string, policy: Policy, purl?: string): boolean {
  const reviewed = purl === undefined ? undefined : policy.exceptions.get(purl);
  return !expressionAllowed(reviewed ?? id, policy.allowed);
}

/** The purl an exception in `x-licence-exceptions` is keyed by (npm packages; the extra records are judged by their own licence). */
const exceptionPurl = (record: PluginPackage) => npmPurl(record.name, record.version);

/**
 * Fails the build for every package whose licence the policy refuses. `rollup-license-plugin` hands its
 * `unacceptableLicenseTest` the licence string only, so an exception keyed by purl could never apply there; the
 * judgement is made here instead, where name and version are known.
 */
export function checkLicences(packages: readonly PluginPackage[], extra: readonly PluginPackage[], policy: Policy): void {
  const refused = merged(packages, extra)
    .filter(({ record, isExtra }) => isUnacceptableLicence(record.license, policy, isExtra ? undefined : exceptionPurl(record)))
    .map(({ record }) => `"${record.license}" for ${record.name}@${record.version}`);
  if (refused.length > 0) throw new Error(`Found unacceptable license ${refused.join(", ")}`);
}

// ---- the lists --------------------------------------------------------------------------------------

/** `name` of `frontend/package.json`: the project itself is not one of its own dependencies. */
export function projectName(): string {
  return (JSON.parse(readText("package.json")) as { name: string }).name;
}

// zxing-cpp is compiled into zxing-wasm's `.wasm`, so no bundler module names it. 3.1.1 is the release the
// pinned commit of zxing-wasm 3.1.6 (`ZXING_CPP_COMMIT`, 2c3dcfe) builds on; its licence text is the one the
// image already ships under /licenses/.
const ZXING_CPP_VERSION = "3.1.1";

export const EXTRA_RECORDS: readonly PluginPackage[] = [
  {
    name: "zxing-cpp",
    version: ZXING_CPP_VERSION,
    license: "Apache-2.0",
    licenseText: readText("licenses/zxing-cpp-Apache-2.0.txt"),
    repository: "https://github.com/zxing-cpp/zxing-cpp",
  },
];

/** Components that are not npm packages: name to the `owner/repo` of their `pkg:github` purl. */
const GITHUB_COMPONENTS: ReadonlyMap<string, string> = new Map([["zxing-cpp", "zxing-cpp/zxing-cpp"]]);

/** Only a web address is ever offered as a link: `git+https://` and `git://` are rewritten, the rest dropped. */
function webAddress(repository: string | null | undefined): string | null {
  if (!repository) return null;
  const url = repository.replace(/^git\+/, "").replace(/^git:\/\//, "https://");
  return /^https?:\/\//i.test(url) ? url : null;
}

function npmPurl(name: string, version: string): string {
  return `pkg:npm/${name.startsWith("@") ? `%40${name.slice(1)}` : name}@${version}`;
}

const byName = (a: PluginPackage, b: PluginPackage) => {
  const left = a.name.toLowerCase();
  const right = b.name.toLowerCase();
  return left < right ? -1 : left > right ? 1 : a.version < b.version ? -1 : a.version > b.version ? 1 : 0;
};

/** The plugin's packages and the extra records, once per name and version, sorted. */
function merged(packages: readonly PluginPackage[], extra: readonly PluginPackage[]) {
  const seen = new Map<string, { record: PluginPackage; isExtra: boolean }>();
  for (const [records, isExtra] of [[packages, false], [extra, true]] as const) {
    for (const record of records) {
      const key = `${record.name}@${record.version}`;
      if (!seen.has(key)) seen.set(key, { record, isExtra });
    }
  }
  return [...seen.values()].sort((a, b) => byName(a.record, b.record));
}

// The Scalar packages that ship no licence file (api-reference, schemas, workspace-store, openapi-types) are
// published from one repository under one MIT licence; the text of the standalone bundle covers them.
const SCALAR_MIT_TEXT = readText("licenses/scalar-api-reference-MIT.txt");

function licenceText(record: PluginPackage): string | null {
  if (record.licenseText) return record.licenseText;
  return record.license === "MIT" && record.name.startsWith("@scalar/") ? SCALAR_MIT_TEXT : null;
}

/** `frontend.json`: name, version, license, licenseText and repository of every package the bundle ships. */
export function toLicenceList(packages: readonly PluginPackage[], extra: readonly PluginPackage[]): string {
  const records = merged(packages, extra).map(({ record }) => ({
    name: record.name,
    version: record.version,
    license: record.license,
    licenseText: licenceText(record),
    repository: webAddress(record.repository),
  }));
  return JSON.stringify(records, null, 2);
}

/** `frontend.cdx.json`: CycloneDX 1.6, reproducible (no serial number, no timestamp). */
export function toCycloneDx(packages: readonly PluginPackage[], extra: readonly PluginPackage[], version: string, name: string): string {
  const components = merged(packages, extra)
    .map(({ record, isExtra }) => {
      const github = isExtra ? GITHUB_COMPONENTS.get(record.name) : undefined;
      return {
        type: "library",
        name: record.name,
        version: record.version,
        purl: github ? `pkg:github/${github}@${record.version}` : npmPurl(record.name, record.version),
        licenses: [{ expression: record.license }],
      };
    })
    .sort((a, b) => (a.purl < b.purl ? -1 : a.purl > b.purl ? 1 : 0));
  return JSON.stringify(
    { bomFormat: "CycloneDX", specVersion: "1.6", version: 1, metadata: { component: { type: "application", name, version } }, components },
    null,
    2,
  );
}

// ---- code the bundler does not see ------------------------------------------------------------------

/** Where `dependency` resolves to from the package at `dir`: every `node_modules` above it, nearest first (Node's lookup). */
function findPackage(dir: string, dependency: string): string | undefined {
  for (let up = dir; ; up = dirname(up)) {
    if (basename(up) === "node_modules") {
      const candidate = join(up, dependency);
      if (existsSync(join(candidate, "package.json"))) return candidate;
    }
    if (dirname(up) === up) return undefined;
  }
}

/**
 * Packages whose code ships although no module of the main bundle names them: Scalar's standalone bundle is
 * copied verbatim (so its whole production tree counts), the code reader's worker is built apart, the fonts are
 * CSS and files (no module), and the service worker inlines four workbox modules at build time.
 */
export async function extraPackagePaths(): Promise<string[]> {
  const paths = new Set<string>();
  const add = (path: string) => paths.add(realpathSync(path));

  // Scalar's tree follows `dependencies` only. `pnpm list` also reports resolved peer and optional dependencies
  // (it puts vite and typescript below Scalar), which are not installed for it and never ship.
  const walk = (dir: string) => {
    const real = realpathSync(dir);
    if (paths.has(real)) return;
    paths.add(real);
    const meta = JSON.parse(readFileSync(join(real, "package.json"), "utf8")) as { dependencies?: Record<string, string> };
    for (const dependency of Object.keys(meta.dependencies ?? {})) {
      // pnpm keeps a package's dependencies beside it; a hoisted layout finds them further up.
      const found = findPackage(real, dependency);
      if (!found) throw new Error(`${dependency} (a dependency of ${real}) is not installed`);
      walk(found);
    }
  };
  walk(join(frontendDir, "node_modules", "@scalar", "api-reference"));
  for (const name of ["zxing-wasm", "@fontsource/atkinson-hyperlegible", "@fontsource/atkinson-hyperlegible-mono"]) {
    add(join(frontendDir, "node_modules", name));
  }
  // pnpm keeps a package's own dependencies next to it, so the workbox modules sit beside workbox-build.
  const beside = dirname(realpathSync(join(frontendDir, "node_modules", "workbox-build")));
  for (const name of ["workbox-core", "workbox-precaching", "workbox-routing", "workbox-strategies"]) add(join(beside, name));
  return [...paths];
}
