import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import type { Page } from "@playwright/test";
import { MAIN } from "./env";
import { expect, mainKey, signInWith, test } from "./fixtures";

const SHOTS = process.env.E2E_SHOTS_DIR;
const shot = async (page: Page, name: string, fullPage = false) => {
  if (!SHOTS) return;
  mkdirSync(SHOTS, { recursive: true });
  await page.screenshot({ path: resolve(SHOTS, name), fullPage });
};
const noSideScroll = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);

/**
 * Everything that would show the CSP or a CDN getting in the way: any `securitypolicyviolation`
 * (with its directive, file and sample), page errors and requests to other origins. Call it
 * before the first navigation so the page load is covered too.
 */
async function watch(page: Page) {
  const problems: string[] = [];
  await page.exposeFunction("__reportCsp", (report: string) => problems.push(report));
  await page.addInitScript(() => {
    document.addEventListener("securitypolicyviolation", (e) =>
      (window as unknown as { __reportCsp(r: string): void }).__reportCsp(`csp ${e.violatedDirective} ${e.sourceFile}:${e.lineNumber} ${e.blockedURI} ${e.sample}`),
    );
  });
  page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));
  page.on("request", (r) => {
    if (!r.url().startsWith(MAIN.url) && !r.url().startsWith("data:") && !r.url().startsWith("blob:")) problems.push(`off-origin request: ${r.url()}`);
  });
  return problems;
}

// One sign-in per project: the hub limits sign-ins per minute for the whole run. Each project
// has its own browser (its fake camera shows its own code), so each signs in once.
test.describe.serial("scan", () => {
  let page: Page;
  test.beforeAll(async ({ browser }) => {
    page = await (await browser.newContext({ baseURL: MAIN.url, viewport: { width: 390, height: 844 }, permissions: ["camera"] })).newPage();
    await page.goto("/");
    await signInWith(page, mainKey());
    await expect(page.getByRole("navigation", { name: /^(Main|Tabs)$/ }).first()).toBeVisible();
  });
  test.afterAll(async () => {
    await page.context().close();
  });

  test("@qr the centre Scan tab opens the camera and a QR label leads to its item", async ({ browser }) => {
    // A second window on the same session, without the service worker: with it active, the
    // worker's own requests would bypass the route below and the reader would not wait.
    const context = await browser.newContext({
      baseURL: MAIN.url,
      viewport: { width: 390, height: 844 },
      permissions: ["camera"],
      storageState: await page.context().storageState(),
      serviceWorkers: "block",
    });
    const cam = await context.newPage();
    const problems = await watch(cam);
    await cam.goto("/");
    await expect(cam.getByRole("navigation", { name: "Tabs" })).toBeVisible();
    // Hold the reader's WebAssembly back so the camera view can be looked at before the first read.
    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    await cam.route("**/*.wasm", async (route) => {
      await gate;
      await route.continue();
    });

    await cam.setViewportSize({ width: 390, height: 844 });
    await cam.getByRole("navigation", { name: "Tabs" }).getByRole("link", { name: "Scan" }).click();
    await expect(cam).toHaveURL(/\/scan$/);
    await expect(cam.getByRole("heading", { level: 1, name: "Scan" })).toBeVisible();
    await expect(cam.getByText("Hold a label's code inside the corners")).toBeVisible();
    await expect.poll(() => cam.locator("video").evaluate((v: HTMLVideoElement) => v.videoWidth)).toBeGreaterThan(0);
    await shot(cam, "task-14-scan-phone-camera.png");
    expect(await noSideScroll(cam)).toBe(true);

    release();
    await expect(cam).toHaveURL(/\/asset\/42$/, { timeout: 20_000 });
    await expect(cam.getByRole("heading", { level: 1, name: "Snipe-IT item" })).toBeVisible();
    // The camera is off again once the screen is left.
    await expect.poll(() => cam.evaluate(() => document.querySelectorAll("video").length)).toBe(0);
    await context.close();
    expect(problems).toEqual([]);
  });

  test("@qr the global search finds printers and jobs, and / focuses it", async () => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/");
    const search = page.getByRole("combobox", { name: "Search" });
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await page.locator("body").click({ position: { x: 700, y: 400 } });
    await page.keyboard.press("/");
    await expect(search).toBeFocused();

    await search.fill("workshop");
    const printer = page.getByRole("option", { name: /Workshop PT-P750W/ });
    await expect(printer).toBeVisible();
    // Integration lookups stay first.
    await expect(page.getByRole("option").first()).toContainText("Look up workshop in");
    await shot(page, "task-14-search-desktop.png");
    await printer.click();
    await expect(page).toHaveURL(/\/printers\/[0-9a-f-]{36}$/);

    const jobs = (await (await page.request.get("/api/jobs?limit=50")).json()) as Array<{ id: string }>;
    expect(jobs.length).toBeGreaterThan(0);
    const id = jobs[0]!.id;
    await page.keyboard.press("/");
    await search.fill(id.slice(0, 6));
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(page.getByRole("option", { name: new RegExp(id.slice(0, 8)) })).toBeVisible();
    await shot(page, "task-14-search-phone.png");
    expect(await noSideScroll(page)).toBe(true);
    await page.getByRole("option", { name: new RegExp(id.slice(0, 8)) }).click();
    await expect(page).toHaveURL(new RegExp(`/jobs/${id}$`));
  });

  test("@qr installable: manifest, active service worker, and /api is never cached", async () => {
    await page.goto("/");
    const manifest = await page.request.get("/manifest.webmanifest");
    expect(manifest.ok()).toBe(true);
    expect(manifest.headers()["content-type"]).toContain("manifest");
    expect(await page.locator('link[rel="manifest"]').getAttribute("href")).toBe("/manifest.webmanifest");

    const state = await page.evaluate(async () => {
      const registration = await navigator.serviceWorker.ready;
      const scope = registration.scope;
      // Touch the API from the page, then look at everything the worker has stored.
      await fetch("/api/info");
      await fetch("/api/jobs?limit=5");
      const urls: string[] = [];
      for (const name of await caches.keys()) for (const request of await (await caches.open(name)).keys()) urls.push(new URL(request.url).pathname);
      return { scope, urls };
    });
    expect(state.scope).toBe(`${MAIN.url}/`);
    expect(state.urls).toContain("/index.html");
    expect(state.urls.filter((u) => /^\/(api|docs|openapi|redoc)/.test(u))).toEqual([]);
  });

  test("@qr without HTTPS the scan screen says so and offers a photo", async ({ browser }) => {
    const context = await browser.newContext({ baseURL: MAIN.url, viewport: { width: 390, height: 844 }, storageState: await page.context().storageState() });
    // The hub is on localhost here, which is secure; pretend it is a plain-HTTP address.
    await context.addInitScript(() => Object.defineProperty(window, "isSecureContext", { value: false }));
    const other = await context.newPage();
    await other.goto("/scan");
    await expect(other.getByText(/needs a secure connection \(HTTPS\) or localhost/)).toBeVisible();
    await expect(other.getByLabel("Choose a photo of a code")).toBeAttached();
    await shot(other, "task-14-scan-phone-insecure.png");
    expect(await noSideScroll(other)).toBe(true);
    await context.close();
  });

  test("@data-matrix zxing worker decodes a data-matrix image under the production CSP", async () => {
    const problems = await watch(page);
    // Make sure the browser's own detector cannot be the one reading this.
    await page.addInitScript(() => Object.defineProperty(window, "BarcodeDetector", { value: undefined, configurable: true }));
    const wasm = page.waitForResponse((r) => /zxing_reader-.*\.wasm$/.test(r.url()));
    await page.goto("/");
    await page.getByRole("navigation", { name: "Tabs" }).getByRole("link", { name: "Scan" }).click();
    await expect(page).toHaveURL(/\/spool\/5$/, { timeout: 20_000 });
    const response = await wasm;
    expect(response.url().startsWith(MAIN.url)).toBe(true);
    expect(response.headers()["content-type"]).toBe("application/wasm");
    expect(await page.evaluate(() => (window as { BarcodeDetector?: unknown }).BarcodeDetector)).toBeUndefined();
    expect(problems).toEqual([]);
  });
});
