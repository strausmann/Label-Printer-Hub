// Shrinks the README screenshots in docs/screenshots/ and fails when one is over budget.
// `oxipng` is optional: without it on PATH the files are left as the browser wrote them and the
// budget check still runs. Run by `pnpm screenshots` after the screenshots were taken.
import { spawnSync } from "node:child_process";
import { readdirSync, statSync } from "node:fs";
import { resolve } from "node:path";

const DIR = resolve(import.meta.dirname, "..", "..", "docs", "screenshots");
const BUDGET_BYTES = 300 * 1024;

const files = readdirSync(DIR)
  .filter((name) => name.endsWith(".png"))
  .sort()
  .map((name) => resolve(DIR, name));
if (files.length === 0) {
  console.error(`No screenshots in ${DIR}`);
  process.exit(1);
}

const has = spawnSync("oxipng", ["--version"], { encoding: "utf8" });
if (has.error || has.status !== 0) {
  console.log("oxipng is not on PATH: the screenshots are not recompressed (install it to shrink them).");
} else {
  const run = spawnSync("oxipng", ["-o", "4", "--strip", "safe", ...files], { stdio: "inherit" });
  if (run.status !== 0) process.exit(run.status ?? 1);
}

const over = files.filter((file) => statSync(file).size > BUDGET_BYTES);
for (const file of over) console.error(`${file} is ${statSync(file).size} bytes, over the ${BUDGET_BYTES} byte budget`);
if (over.length > 0) process.exit(1);
console.log(`${files.length} screenshots, all within ${BUDGET_BYTES / 1024} KB.`);
