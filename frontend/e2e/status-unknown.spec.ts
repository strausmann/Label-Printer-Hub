// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test } from "./fixtures";

const SHOTS = process.env.E2E_SHOTS_DIR;

test.use({ serviceWorkers: "block" }); // the page itself must go through page.route

test.describe("a status nobody refreshes", () => {
  test("a stale and an unpolled printer are shown as unknown, never as ready", async ({ signedInPage: page }) => {
    // The tape printer gets a 143-day-old probe, the page printer is not polled.
    const printers = (await (await page.request.get("/api/v1/printers")).json()) as { id: string; name: string }[];
    const roles = new Map<string, "stale" | "unpolled">();
    for (const p of printers) {
      if (p.name === "Workshop PT-P750W") roles.set(p.id, "stale");
      if (p.name === "Office page printer") roles.set(p.id, "unpolled");
    }
    await page.route(/\/api\/v1\/printers\/[^/]+\/status$/, async (route) => {
      const response = await route.fetch();
      const body = (await response.json()) as Record<string, unknown>;
      const id = String(body.printer_id);
      const role = roles.get(id);
      if (role === "stale") {
        Object.assign(body, { online: null, polled: true, stale: true, tape_loaded: null, last_probe_age_s: 12349795, note: "Status older than 90 s" });
      } else if (role === "unpolled") {
        Object.assign(body, { online: null, polled: false, tape_loaded: null, note: "Not polled" });
      }
      await route.fulfill({ response, json: body });
    });

    for (const [width, height] of [
      [1280, 800],
      [390, 844],
    ] as const) {
      for (const scheme of ["light", "dark"] as const) {
        await page.setViewportSize({ width, height });
        await page.emulateMedia({ colorScheme: scheme });
        await page.goto("/printers");
        await expect(page.getByRole("heading", { level: 1, name: "Printers" })).toBeVisible();
        await expect(page.getByText("Status unknown").first()).toBeVisible();
        await expect(page.getByText("Not monitored").first()).toBeVisible();
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
        if (SHOTS) {
          mkdirSync(SHOTS, { recursive: true });
          await page.screenshot({ path: resolve(SHOTS, `task-8-printers-${width}-${scheme}.png`), fullPage: true });
        }
      }
    }

    // Detail page of the stale printer: age in the user's words.
    await page.setViewportSize({ width: 390, height: 844 });
    const staleId = [...roles].find(([, r]) => r === "stale")![0];
    await page.goto(`/printers/${staleId}`);
    await expect(page.getByText("Last status 142 days ago")).toBeVisible();
    await expect(page.getByText("Tape not known")).toBeVisible();
    await expect(page.getByText("Ready")).toHaveCount(0);
    if (SHOTS) await page.screenshot({ path: resolve(SHOTS, "task-8-detail-390-dark.png"), fullPage: true });
  });
});
