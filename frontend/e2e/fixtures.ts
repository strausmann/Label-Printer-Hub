import { readFileSync } from "node:fs";
import { test as base, expect, type APIRequestContext, type Page } from "@playwright/test";
import { BOOTSTRAP, MAIN } from "./env";

/** The key the test hub wrote for us: plaintext, never logged. */
export const mainKey = () => readFileSync(MAIN.keyFile, "utf8").trim();
export const bootstrapKey = () => readFileSync(BOOTSTRAP.keyFile, "utf8").trim();

/** Fills the sign-in screen and waits until the shell is there. */
export async function signInWith(page: Page, key: string): Promise<void> {
  await page.getByLabel("API key").fill(key);
  await page.getByRole("button", { name: "Sign in" }).click();
}

/** What `GET /__e2e/page-printer` answers: the fake's address and what it currently reports. */
export type PagePrinterControl = { uri: string; state: Record<string, unknown> };

/** The state the fake page printer can be switched to (test-only control path, loopback only). */
export type PagePrinterState = {
  printer_state?: number;
  reasons?: string[];
  markers?: { name: string; color?: string; level?: number; low_level?: number; type?: string }[];
  accepting_jobs?: boolean;
  job_script?: number[];
  /** Hardware margins the printer reports, in hundredths of a millimetre. */
  margins_hmm?: number;
  /** Polls that report "stopping" after a Cancel-Job. */
  cancel_steps?: number;
  /** The `media-default` keyword the printer reports; `""` stops it reporting one. */
  media_default?: string;
  /** The `printer-uuid` the printer reports: the identity the hub stores; `""` stops it reporting one. */
  printer_uuid?: string;
};

/** Switches the fake page printer; the hub notices on its next status probe (1 s in the test hub). */
export async function setPagePrinter(page: Page, state: PagePrinterState): Promise<void> {
  const response = await page.request.post(`${MAIN.url}/__e2e/page-printer/state`, { data: state });
  expect(response.ok(), await response.text()).toBe(true);
}

/**
 * Waits until the hub's cached status of the page printer was captured twice after this call.
 *
 * `setPagePrinter` returns as soon as the fake has switched; the hub still holds the previous reading
 * until its next probe. The first new `captured_at` may belong to a probe that was already running
 * before the switch, so the second one is the first reading that surely shows it. A test whose
 * outcome depends on that reading (the hub decides from its cache, e.g. the paper size of a test
 * print) calls this before it acts; a slow runner otherwise acts on the old reading.
 */
export async function waitForFreshProbe(page: Page): Promise<void> {
  const list = (await (await page.request.get(`${MAIN.url}/api/v1/printers`)).json()) as { id: string; name: string }[];
  const id = list.find((p) => p.name === "Office page printer")!.id;
  const capturedAt = async () => ((await (await page.request.get(`${MAIN.url}/api/v1/printers/${id}/status`)).json()) as { captured_at?: string | null }).captured_at ?? null;
  const seen = new Set<string | null>([await capturedAt()]);
  await expect
    .poll(
      async () => {
        seen.add(await capturedAt());
        return seen.size;
      },
      { message: "the hub did not capture the page printer's status twice", timeout: 15_000, intervals: [100, 200, 400] },
    )
    .toBeGreaterThanOrEqual(3);
}

/**
 * Puts the fake page printer back to idle and ready. Every spec that switches it calls this in `afterEach`.
 * It then waits until the hub's queue for that printer is empty again (see `waitForQuietQueue`).
 */
export async function resetPagePrinter(page: Page): Promise<void> {
  const response = await page.request.post(`${MAIN.url}/__e2e/page-printer/reset`);
  expect(response.ok(), await response.text()).toBe(true);
  await waitForQuietQueue(page);
}

/**
 * Waits until no job is queued or printing for the page printer and the hub has not paused it.
 *
 * The fake printer is not the only shared state: the hub's print queue is too. A job that is still
 * queued behind a running one is dispatched when that one ends, and if the printer is stopped by
 * then, the queue defers the job and PAUSES the printer until the stop is cleared. A spec that sets a
 * stopped state at that moment (printers.spec does) sees "Paused" where it expects "Stopped".
 * Specs that start jobs and end without waiting for them hand such a queue to the next spec.
 */
export async function waitForQuietQueue(page: Page): Promise<void> {
  const named = async () => {
    const list = await page.request.get(`${MAIN.url}/api/v1/printers`);
    if (!list.ok()) return null; // not signed in: there is no queue to ask about
    const printers = (await list.json()) as { id: string; name: string; paused?: boolean }[];
    return printers.find((p) => p.name === "Office page printer") ?? null;
  };
  const printer = await named();
  if (!printer) return;
  await expect
    .poll(
      async () => {
        const queue = await page.request.get(`${MAIN.url}/api/v1/printers/${printer.id}/queue`);
        const jobs = queue.ok() ? ((await queue.json()) as unknown[]).length : -1;
        return { jobs, paused: (await named())?.paused ?? null };
      },
      { message: "the hub still has page jobs in flight or the page printer paused", timeout: 60_000, intervals: [250, 500, 1000] },
    )
    .toEqual({ jobs: 0, paused: false });
}

/** The fake's `ipp://` address and its current state. */
export async function pagePrinterControl(page: Page): Promise<PagePrinterControl> {
  const response = await page.request.get(`${MAIN.url}/__e2e/page-printer`);
  expect(response.headers()["content-type"]).toContain("application/json");
  return (await response.json()) as PagePrinterControl;
}

/**
 * Discards every held tape run of the e2e key.
 *
 * Held runs live in the hub's queue for the whole e2e session, not per test: a job another spec
 * retried on a mock printer that refuses it stays as a stopped run ("Tape prints that wait for
 * you"), and a batch left between its parts waits for ever. Both would show up in a later spec
 * and make its outcome depend on which specs ran before it. The API key needs no CSRF token.
 */
export async function discardHeldRuns(request: APIRequestContext): Promise<void> {
  const list = await request.get("/api/v1/batches/runs/held");
  expect(list.ok(), await list.text()).toBe(true);
  const held = (await list.json()) as Array<{ batch_id: string }>;
  for (const run of held) {
    const response = await request.post(`/api/v1/batches/${run.batch_id}/discard`);
    expect(response.status(), await response.text()).toBe(204);
  }
}

export const test = base.extend<{ signedInPage: Page; cleanHeldRuns: void }>({
  // Automatic: every test of every spec starts without held runs (263-71).
  cleanHeldRuns: [
    async ({ playwright }, use) => {
      const request = await playwright.request.newContext({ baseURL: MAIN.url, extraHTTPHeaders: { "X-Label-Hub-Key": mainKey() } });
      try {
        await discardHeldRuns(request);
        await use();
      } finally {
        await request.dispose();
      }
    },
    { auto: true },
  ],
  signedInPage: async ({ page }, use) => {
    await page.goto("/");
    await signInWith(page, mainKey());
    await expect(page.getByRole("navigation", { name: /^(Main|Tabs)$/ }).first()).toBeVisible();
    await use(page);
    // A route handler that is still inside `route.fetch()` when the test ends throws "Test ended"
    // into whatever test is reported next. Drop every route and let in-flight handlers fail quietly.
    await page.unrouteAll({ behavior: "ignoreErrors" });
  },
});

export { expect };
