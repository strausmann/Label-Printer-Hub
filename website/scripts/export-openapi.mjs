// Writes the backend's OpenAPI document to openapi/labelyard.json for the API reference.
// Runs backend/scripts/export_openapi.py (no server, placeholder settings). The interpreter is
// $PYTHON, else python3; the backend and its dependencies must be installed in it
// (`pip install -e backend`). With --check it only compares and exits 1 when the file is stale.
import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const site = join(dirname(fileURLToPath(import.meta.url)), "..");
const backend = join(site, "..", "backend");
const target = join(site, "openapi", "labelyard.json");
const python = process.env.PYTHON || "python3";

const run = spawnSync(python, ["scripts/export_openapi.py"], {
  cwd: backend,
  encoding: "utf8",
  maxBuffer: 64 * 1024 * 1024,
});
if (run.error || run.status !== 0) {
  console.error(run.stderr || String(run.error));
  console.error(`export-openapi: ${python} backend/scripts/export_openapi.py failed`);
  console.error("Install the backend first: pip install -e backend (or set PYTHON).");
  process.exit(1);
}

if (process.argv.includes("--check")) {
  const current = existsSync(target) ? readFileSync(target, "utf8") : "";
  if (current !== run.stdout) {
    console.error("export-openapi: website/openapi/labelyard.json is stale; run pnpm -C website build");
    process.exit(1);
  }
  console.log("export-openapi: up to date");
} else {
  mkdirSync(dirname(target), { recursive: true });
  writeFileSync(target, run.stdout);
  console.log(`export-openapi: wrote ${target}`);
}
