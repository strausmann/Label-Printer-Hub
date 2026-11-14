// node --test frontend/scripts/optimise-screenshots.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";
import { BUDGET_BYTES, overBudget, plan, webpName } from "./optimise-screenshots.mjs";

test("a website shot keeps its name and gets the webp extension", () => {
  assert.equal(webpName("hero.de.dark.png"), "hero.de.dark.webp");
  assert.equal(webpName("printer-detail.en.light.png"), "printer-detail.en.light.webp");
});

test("README files and unknown languages or themes are not website shots", () => {
  assert.equal(webpName("overview-light.png"), null);
  assert.equal(webpName("hero.fr.light.png"), null);
  assert.equal(webpName("hero.en.sepia.png"), null);
  assert.equal(webpName("hero.en.light.webp"), null);
});

test("plan keeps only website shots, sorted", () => {
  assert.deepEqual(plan(["jobs.en.dark.png", "notes.txt", "hero.de.light.png", "overview-dark.png"]), [
    { png: "hero.de.light.png", webp: "hero.de.light.webp" },
    { png: "jobs.en.dark.png", webp: "jobs.en.dark.webp" },
  ]);
});

test("a file over the budget is reported, one at the budget is not", () => {
  const files = [
    { name: "a.en.light.webp", size: BUDGET_BYTES },
    { name: "b.en.dark.webp", size: BUDGET_BYTES + 1 },
  ];
  assert.deepEqual(overBudget(files), [files[1]]);
});
