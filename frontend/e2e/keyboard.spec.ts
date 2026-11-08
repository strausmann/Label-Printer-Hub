import type { Page } from "@playwright/test";
import { MAIN } from "./env";
import { expect, mainKey, signInWith, test } from "./fixtures";

// Acceptance 23, keyboard only: on every page of the sheet archive work, at 360 px in both
// languages, Tab alone reaches every control in the content, each focused control shows a ring,
// and focus does not get stuck. The pages are opened by address (the routes are not gated).

const SEED_TYPE = "avery-zweckform-l4736rev";
const PARTLY_USED = "L4736-0001";
const EDGE = "L4731-0001";
const setLanguage = (page: Page, lang: "de" | "en") => page.evaluate((l) => localStorage.setItem("lph.lang", l), lang);

async function printerId(page: Page): Promise<string> {
  const printers = (await (await page.request.get("/api/printers")).json()) as Array<{ id: string; name: string; kind?: string }>;
  return printers.find((p) => p.name === "Office page printer")!.id;
}

type Report = { reached: number; candidates: number; missed: string[]; noRing: string[]; stuck: boolean };

/**
 * Presses Tab from the start of the content until focus leaves it, then compares what was
 * focused with every control of the content that is in the tab order. This is a check of the
 * page, not of a library: a control that is in the tab order and never gets focus is a trap.
 */
async function tabThrough(page: Page): Promise<Report> {
  await page.evaluate(() => {
    const content = document.querySelector<HTMLElement>("#content")!;
    const describe = (el: Element) => `${el.tagName.toLowerCase()}[${(el.getAttribute("aria-label") || el.textContent || el.getAttribute("name") || "").trim().slice(0, 40)}]`;
    const visible = (el: HTMLElement) => {
      const style = getComputedStyle(el);
      if (style.visibility === "hidden" || style.display === "none") return false;
      if (el.closest("[inert], [aria-hidden='true']")) return false;
      return el.getClientRects().length > 0;
    };
    const candidates = [...content.querySelectorAll<HTMLElement>("a[href], button, input, select, textarea, summary, [tabindex]")].filter(
      (el) => el.tabIndex >= 0 && !(el as HTMLButtonElement).disabled && visible(el),
    );
    candidates.forEach((el, i) => el.setAttribute("data-kbd", String(i)));
    (window as unknown as { __kbd: unknown }).__kbd = { candidates: candidates.map(describe), reached: new Set<number>(), noRing: [] as string[] };
    content.focus();
  });
  const total = await page.evaluate(() => (window as unknown as { __kbd: { candidates: string[] } }).__kbd.candidates.length);
  let stuck = false;
  let last = "";
  let same = 0;
  for (let i = 0; i < total + 6; i++) {
    await page.keyboard.press("Tab");
    const state = await page.evaluate(() => {
      const kbd = (window as unknown as { __kbd: { reached: Set<number>; noRing: string[] } }).__kbd;
      const el = document.activeElement as HTMLElement | null;
      const content = document.querySelector("#content")!;
      if (!el || !content.contains(el) || el === content) return { inside: false, id: "" };
      const index = el.getAttribute("data-kbd");
      if (index !== null) kbd.reached.add(Number(index));
      const ring = (node: Element) => {
        const s = getComputedStyle(node);
        return (s.outlineStyle !== "none" && parseFloat(s.outlineWidth) > 0) || s.boxShadow !== "none";
      };
      // A sheet cell is an SVG group: its ring is a stroke on an inner shape (`data-ring`), not an outline.
      const stroked = (node: Element) => {
        const stroke = getComputedStyle(node).stroke;
        return stroke !== "none" && stroke !== "rgba(0, 0, 0, 0)" && stroke !== "transparent";
      };
      let ok = ring(el) || [...el.querySelectorAll("[data-ring]")].some(stroked);
      if (!ok) {
        // A visually hidden input (switch, radio) shows its ring on the label or a neighbour.
        const scope = el.closest("label") ?? el.parentElement;
        ok = !!scope && (ring(scope) || [...scope.querySelectorAll("*")].some(ring)) && el.getBoundingClientRect().width < 4;
      }
      if (!ok) kbd.noRing.push(`${el.tagName.toLowerCase()}[${(el.getAttribute("aria-label") || el.textContent || "").trim().slice(0, 40)}]`);
      return { inside: true, id: index ?? el.tagName };
    });
    if (!state.inside) break;
    same = state.id === last ? same + 1 : 0;
    last = state.id;
    if (same >= 3) {
      stuck = true;
      break;
    }
  }
  return page.evaluate(() => {
    const kbd = (window as unknown as { __kbd: { candidates: string[]; reached: Set<number>; noRing: string[] } }).__kbd;
    const missed = kbd.candidates.filter((_, i) => !kbd.reached.has(i));
    return { reached: kbd.reached.size, candidates: kbd.candidates.length, missed, noRing: kbd.noRing, stuck: false };
  }).then((r) => ({ ...r, stuck }));
}

// One sign-in for the whole file: the hub limits sign-ins per minute.
test.describe.serial("keyboard only", () => {
  let page: Page;
  let printer: string;
  test.beforeAll(async ({ browser }) => {
    page = await (await browser.newContext({ baseURL: MAIN.url })).newPage();
    await page.goto("/");
    await signInWith(page, mainKey());
    await expect(page.getByRole("navigation", { name: /^(Main|Tabs)$/ }).first()).toBeVisible();
    printer = await printerId(page);
  });
  test.afterAll(async () => {
    await page.context().close();
  });

  const pages: Array<[string, () => string, RegExp]> = [
    ["sheets", () => "/sheets", /^(Sheets|Bögen)$/],
    ["archive", () => "/sheets/archive", /Sheet archive|Bogenarchiv/],
    ["archive type", () => `/sheets/archive?type=${SEED_TYPE}`, /.+/],
    ["sheet detail", () => `/sheets/${PARTLY_USED}`, /L4736-0001/],
    ["sheet detail, 189 cells", () => `/sheets/${EDGE}`, /L4731-0001/],
    ["calibration", () => `/calibration?printer=${printer}&tray=main-tray`, /Calibration|Kalibrierung/],
    ["printer", () => `/printers/${printer}`, /.+/],
    ["cart onto a sheet", () => `/cart?sheet=${PARTLY_USED}`, /.+/],
  ];

  for (const lang of ["en", "de"] as const) {
    for (const [name, path, heading] of pages) {
      test(`${name}, ${lang} at 360 px: Tab reaches every control, each with a visible ring`, async () => {
        await setLanguage(page, lang);
        await page.setViewportSize({ width: 360, height: 780 });
        if (name === "cart onto a sheet") {
          // The cart holds three Grocy labels and the page printer is the chosen one (own browser context: nothing leaks to other specs).
          await page.evaluate(
            ([id]) => {
              localStorage.setItem("lph.printer", String(id));
              localStorage.setItem("lph.cart", JSON.stringify([{ app: "grocy", id: "7", name: "Flour", content_type: "qr_two_lines", copies: 3 }]));
            },
            [printer] as const,
          );
        }
        await page.goto(path());
        await expect(page.getByRole("heading", { level: 1, name: heading }).first()).toBeVisible();
        // Wait for the data: nothing says "Loading…" any more.
        await expect(page.getByText(/^(Loading…|Lädt…)$/)).toHaveCount(0);
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
        const report = await tabThrough(page);
        expect(report.candidates, "the page has controls").toBeGreaterThan(0);
        expect(report.stuck, "focus is not stuck").toBe(false);
        expect(report.noRing, "controls without a focus ring").toEqual([]);
        expect(report.missed, "controls in the tab order that Tab never reached").toEqual([]);
      });
    }
  }
});
