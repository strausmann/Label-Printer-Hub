// Tests for the locale parity gate: every page exists in English (root) and German (de/).
import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { test } from "node:test";

import { findParityGaps, findScreenshotGaps } from "./check-locale-parity.mjs";

function tree(files) {
  const root = mkdtempSync(join(tmpdir(), "parity-"));
  for (const file of files) {
    const path = join(root, file);
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, "---\ntitle: t\n---\n");
  }
  return root;
}

test("reports a page missing in de", () => {
  const root = tree(["index.mdx", "de/index.mdx", "using/printers.md"]);
  assert.deepEqual(findParityGaps(root), { missingDe: ["using/printers"], missingEn: [] });
});

test("reports a page missing in en", () => {
  const root = tree(["index.mdx", "de/index.mdx", "de/admin/backups.md"]);
  assert.deepEqual(findParityGaps(root), { missingDe: [], missingEn: ["admin/backups"] });
});

test("md and mdx count as the same slug", () => {
  const root = tree(["try/index.md", "de/try/index.mdx"]);
  assert.deepEqual(findParityGaps(root), { missingDe: [], missingEn: [] });
});

test("index pages pair up", () => {
  const root = tree(["index.mdx", "de/index.mdx"]);
  assert.deepEqual(findParityGaps(root), { missingDe: [], missingEn: [] });
});

test("passes on a complete tree", () => {
  const root = tree([
    "index.mdx",
    "de/index.mdx",
    "install/reverse-proxy.md",
    "de/install/reverse-proxy.md",
    "admin/upgrades/index.md",
    "de/admin/upgrades/index.md",
  ]);
  assert.deepEqual(findParityGaps(root), { missingDe: [], missingEn: [] });
});

test("ignores files that are not pages", () => {
  const root = tree(["index.mdx", "de/index.mdx", "notes.txt"]);
  assert.deepEqual(findParityGaps(root), { missingDe: [], missingEn: [] });
});

test("reports a screenshot missing its de dark variant", () => {
  const root = tree([
    "overview.en.light.webp",
    "overview.en.dark.webp",
    "overview.de.light.webp",
  ]);
  assert.deepEqual(findScreenshotGaps(root), ["overview.de.dark.webp"]);
});

test("a missing screenshot folder has no gaps", () => {
  assert.deepEqual(findScreenshotGaps(join(tmpdir(), "no-such-screens-dir")), []);
});
