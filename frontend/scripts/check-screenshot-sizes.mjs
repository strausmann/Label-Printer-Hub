// Fails when a README screenshot in docs/screenshots/ is over budget; it changes no file. The files are
// deliberately not recompressed: an optimiser that ran in one place only would break the byte-identical regeneration.
// Run by `pnpm screenshots` after the screenshots were taken.
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

const over = files.filter((file) => statSync(file).size > BUDGET_BYTES);
for (const file of over) console.error(`${file} is ${statSync(file).size} bytes, over the ${BUDGET_BYTES} byte budget`);
if (over.length > 0) process.exit(1);
console.log(`${files.length} screenshots, all within ${BUDGET_BYTES / 1024} KB.`);
