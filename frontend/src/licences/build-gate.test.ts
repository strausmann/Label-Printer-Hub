// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { afterAll, describe, expect, it } from "vitest";

// Runs `vite build` itself: the check lives in the plugin wiring of vite.config.ts, which a unit test of
// `checkLicences` cannot see. CI runs this file after `pnpm build` (REQUIRE_DIST=1); locally set BUILD_GATE=1.
const run = process.env.REQUIRE_DIST === "1" || process.env.BUILD_GATE === "1";
const frontend = resolve(__dirname, "..", "..");
const policy = JSON.parse(readFileSync(resolve(frontend, "..", "licence-policy.yml"), "utf8")) as Record<string, unknown> & {
  "allow-licenses": string[];
  "x-licence-exceptions": Record<string, string>[];
};
// tslib is the only package under 0BSD in the bundle; remove the licence and exactly that package is refused.
const REFUSED = "0BSD";
const dir = mkdtempSync(join(tmpdir(), "licence-gate-"));
afterAll(() => rmSync(dir, { recursive: true, force: true }));

function build(name: string, exceptions: Record<string, string>[]) {
  const file = join(dir, `${name}.yml`);
  const custom = { ...policy, "allow-licenses": policy["allow-licenses"].filter((l) => l !== REFUSED), "x-licence-exceptions": [...policy["x-licence-exceptions"], ...exceptions] };
  writeFileSync(file, JSON.stringify(custom));
  return spawnSync("pnpm", ["exec", "vite", "build", "--outDir", join(dir, `out-${name}`), "--emptyOutDir"], {
    cwd: frontend,
    env: { ...process.env, LICENCE_POLICY: file },
    encoding: "utf8",
  });
}

describe.skipIf(!run)("the licence gate in the real build", () => {
  it("test_build_fails_on_a_refused_licence_and_names_the_package", { timeout: 170_000 }, () => {
    const result = build("refused", []);
    expect(result.status).not.toBe(0);
    expect(`${result.stdout}${result.stderr}`).toMatch(/unacceptable license "0BSD" for tslib@/);
  });

  it("test_a_purl_exception_lets_that_package_through_the_build", { timeout: 170_000 }, () => {
    const tslib = (JSON.parse(readFileSync(resolve(frontend, "dist", "licenses", "frontend.json"), "utf8")) as { name: string; version: string }[]).find((p) => p.name === "tslib")!;
    const result = build("exception", [{ purl: `pkg:npm/tslib@${tslib.version}`, licence: "MIT", reason: "test" }]);
    expect(`${result.stdout}${result.stderr}`).not.toMatch(/unacceptable/);
    expect(result.status).toBe(0);
  });
});
