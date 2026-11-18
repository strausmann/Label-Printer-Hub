// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { MAIN } from "./env";
import { expect, mainKey, signInWith, test } from "./fixtures";

// Chrome's "Desktop site" mode on a tablet: an X11 user agent on a touch screen. React Aria marks a pointer event
// "virtual" when it is not Android and the touch has a zero-sized contact area, and then ignores the press. A real
// touch reports exactly that zero size, so the switch must not depend on React Aria's press handling (#392).
const DESKTOP_SITE_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36";

test("switches toggle on a zero-radius touch in desktop-site mode and with the keyboard", async ({ browser }) => {
  const setup = await browser.newContext({ baseURL: MAIN.url });
  const login = await setup.newPage();
  await login.goto("/");
  await signInWith(login, mainKey());
  await expect(login.getByRole("navigation", { name: /^(Main|Tabs)$/ }).first()).toBeVisible();
  const storageState = await setup.storageState();
  await setup.close();

  const context = await browser.newContext({
    baseURL: MAIN.url,
    userAgent: DESKTOP_SITE_UA,
    hasTouch: true,
    isMobile: true,
    viewport: { width: 980, height: 1500 },
    storageState,
  });
  try {
    const page = await context.newPage();
    await page.addInitScript(() => localStorage.setItem("lph.lang", "en"));
    await page.goto("/sheets");
    await expect(page.getByRole("heading", { level: 1, name: "Sheets" })).toBeVisible();
    const cdp = await context.newCDPSession(page);

    for (const name of ["Hide used-up sheets", "Show discarded sheets", "Back side missing"]) {
      const input = page.getByRole("switch", { name });
      const label = page.locator("label").filter({ has: input });
      await label.scrollIntoViewIfNeeded();
      const box = await label.boundingBox();
      if (!box) throw new Error(`${name}: no label box`);
      const x = box.x + 22;
      const y = box.y + box.height / 2;

      const before = await input.isChecked();
      await cdp.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x, y, radiusX: 0, radiusY: 0, force: 1 }] });
      await cdp.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
      await expect.poll(() => input.isChecked(), { message: `${name} toggles on a zero-radius touch` }).toBe(!before);

      const afterTouch = await input.isChecked();
      await input.focus();
      await page.keyboard.press("Space");
      await expect.poll(() => input.isChecked(), { message: `${name} toggles on Space` }).toBe(!afterTouch);
    }
  } finally {
    await context.close();
  }
});
