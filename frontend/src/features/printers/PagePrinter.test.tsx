import { screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderApp } from "../../test-utils";
import { job, mockApi, PAGE_PRINTER, PRINTER_A, pageStatus, status } from "../test-api";

afterEach(() => vi.unstubAllGlobals());

const P = PAGE_PRINTER.id;
const reason = (keyword: string, severity: "report" | "warning" | "error", blocking: boolean) => ({ keyword, severity, blocking });
const black = (over: Record<string, unknown> = {}) => ({
  name: "black",
  color: "#000000",
  level_percent: 0,
  low: true,
  empty: false,
  some_remaining: false,
  type: "toner",
  ...over,
});

function listRoutes(pageStat: Record<string, unknown>) {
  return {
    "GET /api/v1/printers": [PAGE_PRINTER, PRINTER_A],
    [`GET /api/v1/printers/${P}/status`]: pageStat,
    [`GET /api/v1/printers/${PRINTER_A.id}/status`]: status(PRINTER_A.id),
    "GET /api/v1/jobs": [],
  };
}
const card = async (name: RegExp) => (await screen.findByRole("link", { name })) as HTMLElement;

describe("page printer card", () => {
  it("stopped with toner low shows Stopped and 'black 0 %, low' (spec 11.3)", async () => {
    mockApi(
      listRoutes(
        pageStatus(P, { printer_state: "stopped", state_reasons: [reason("toner-low", "warning", false)], markers: [black()] }),
      ),
    );
    await renderApp({ path: "/printers" });
    const c = await card(/Office laser/);
    expect(await within(c).findByText("Stopped")).toBeVisible();
    expect(within(c).getByText("toner low")).toBeVisible();
    expect(within(c).getByText("black")).toBeVisible();
    expect(within(c).getByText("0 %, low")).toBeVisible();
  });

  it("shows toner instead of tape, and no tape wording", async () => {
    mockApi(listRoutes(pageStatus(P)));
    await renderApp({ path: "/printers" });
    const c = await card(/Office laser/);
    expect(await within(c).findByText("Black toner")).toBeVisible();
    expect(within(c).queryByText(/tape/i)).toBeNull();
  });

  it("stopped with toner empty and a marker at some remaining names both", async () => {
    mockApi(
      listRoutes(
        pageStatus(P, {
          printer_state: "stopped",
          state_reasons: [reason("toner-empty", "error", true)],
          markers: [black({ level_percent: 0, low: true, empty: true }), black({ name: "cyan", level_percent: null, low: false, some_remaining: true })],
        }),
      ),
    );
    await renderApp({ path: "/printers" });
    const c = await card(/Office laser/);
    expect(await within(c).findByText("toner empty")).toBeVisible();
    expect(within(c).getByText("empty")).toBeVisible();
    expect(within(c).getByText("some remaining")).toBeVisible();
  });

  it("an unknown reason keyword is shown verbatim", async () => {
    mockApi(listRoutes(pageStatus(P, { printer_state: "stopped", state_reasons: [reason("developer-low", "error", true)] })));
    await renderApp({ path: "/printers" });
    expect(await within(await card(/Office laser/)).findByText("developer-low")).toBeVisible();
  });

  it("an idle printer with a blocking reason says it in words, not as a raw code", async () => {
    mockApi(
      listRoutes(
        pageStatus(P, { error_state: "media-empty", state_reasons: [reason("media-empty", "error", true)] }),
      ),
    );
    await renderApp({ path: "/printers" });
    const c = await card(/Office laser/);
    expect(await within(c).findByText("Problem")).toBeVisible();
    expect(within(c).getByText("media empty")).toBeVisible();
    expect(within(c).queryByText("media-empty")).toBeNull();
  });

  it("an idle printer with an unknown blocking keyword shows it verbatim, not in the code font", async () => {
    mockApi(
      listRoutes(
        pageStatus(P, { error_state: "developer-low", state_reasons: [reason("developer-low", "error", true)] }),
      ),
    );
    await renderApp({ path: "/printers" });
    const c = await card(/Office laser/);
    expect(await within(c).findByText("developer-low")).toBeVisible();
    expect(c.querySelector("code")).toBeNull();
  });

  it("the detail page of a page printer shows its blocking reason in words", async () => {
    mockApi({
      [`GET /api/v1/printers/${P}`]: PAGE_PRINTER,
      [`GET /api/v1/printers/${P}/status`]: pageStatus(P, { error_state: "cover-open", state_reasons: [reason("cover-open", "error", true)] }),
      [`GET /api/v1/printers/${P}/queue`]: [],
    });
    await renderApp({ path: `/printers/${P}` });
    expect(await screen.findByText("cover open")).toBeVisible();
    expect(screen.queryByText("cover-open")).toBeNull();
  });

  it("a tape printer with error flags keeps its error text on the card", async () => {
    mockApi({
      ...listRoutes(pageStatus(P)),
      [`GET /api/v1/printers/${PRINTER_A.id}/status`]: status(PRINTER_A.id, { error_state: "cover open" }),
    });
    await renderApp({ path: "/printers" });
    const c = await card(/Workshop PT-P750W/);
    expect(await within(c).findByText("Problem")).toBeVisible();
    expect(within(c).getByText("cover open")).toBeVisible();
  });

  it("a printer that never answered says so and invents no supplies (#206)", async () => {
    mockApi(listRoutes(pageStatus(P, { online: null, printer_state: null, markers: [], trays: [], state_reasons: [] })));
    await renderApp({ path: "/printers" });
    const c = await card(/Office laser/);
    expect(await within(c).findByText("No answer yet")).toBeVisible();
    expect(within(c).queryByText("No supplies reported")).toBeNull();
  });

  it("a tape printer's card is unchanged: tape, no toner, no page wording", async () => {
    mockApi(listRoutes(pageStatus(P)));
    await renderApp({ path: "/printers" });
    await card(/Office laser/);
    const c = await card(/Workshop PT-P750W/);
    expect(await within(c).findByText("Ready")).toBeVisible();
    expect(within(c).getByText("12 mm")).toBeVisible();
    expect(within(c).getByText("Blue")).toBeVisible();
    expect(within(c).queryByText(/toner|supplies|answer/i)).toBeNull();
  });
});

describe("page printer detail", () => {
  const routes = (pageStat: Record<string, unknown>, extra: Record<string, unknown> = {}) => ({
    [`GET /api/v1/printers/${P}`]: PAGE_PRINTER,
    [`GET /api/v1/printers/${P}/status`]: pageStat,
    [`GET /api/v1/printers/${P}/queue`]: [],
    [`GET /api/v1/printers/${P}/calibration`]: [
      { tray: "main", offset_x_mm: 0.4, offset_y_mm: -0.2, scale_x: 1, scale_y: 1, rotation_deg: 0.1, method: "manual", updated_at: "2026-11-03T10:00:00Z", measured_on: null },
      { tray: "bypass", offset_x_mm: null, offset_y_mm: null, scale_x: null, scale_y: null, rotation_deg: null, method: null, updated_at: null, measured_on: null },
    ],
    ...extra,
  });
  const CAL = { features: { calibration: true } };

  it("lists the trays with their load hints and media", async () => {
    mockApi(routes(pageStatus(P)));
    await renderApp({ path: `/printers/${P}` });
    const trays = await screen.findByRole("region", { name: "Trays" });
    expect(await within(trays).findByText("Main tray")).toBeVisible();
    expect(within(trays).getByText("Print side up")).toBeVisible();
    expect(within(trays).getByText("A4")).toBeVisible();
    expect(within(trays).getByText("Bypass")).toBeVisible();
  });

  it("a printer with no trays reported says so", async () => {
    mockApi(routes(pageStatus(P, { trays: [] })));
    await renderApp({ path: `/printers/${P}` });
    const trays = await screen.findByRole("region", { name: "Trays" });
    expect(await within(trays).findByText("The printer reports no trays.")).toBeVisible();
  });

  it("shows toner under Supplies, not under Material", async () => {
    mockApi(routes(pageStatus(P, { markers: [black()] })));
    await renderApp({ path: `/printers/${P}` });
    const supplies = await screen.findByRole("region", { name: "Supplies" });
    expect(await within(supplies).findByText("0 %, low")).toBeVisible();
    expect(screen.queryByRole("region", { name: "Material" })).toBeNull();
  });

  it("counts jobs from other computers ahead", async () => {
    mockApi(routes(pageStatus(P, { jobs_ahead: 2 })));
    const first = await renderApp({ path: `/printers/${P}` });
    expect(await screen.findByText("2 jobs from other computers ahead")).toBeVisible();
    first.unmount();
    vi.unstubAllGlobals();
    mockApi(routes(pageStatus(P, { jobs_ahead: 1 })));
    await renderApp({ path: `/printers/${P}` });
    expect(await screen.findByText("1 job from another computer ahead")).toBeVisible();
  });

  it("says nothing about other jobs when none are ahead", async () => {
    mockApi(routes(pageStatus(P, { jobs_ahead: 0 })));
    await renderApp({ path: `/printers/${P}` });
    await screen.findByRole("region", { name: "Trays" });
    expect(screen.queryByText(/other computer/)).toBeNull();
  });

  it("summarises calibration per tray with a typed link to the calibration page", async () => {
    mockApi(routes(pageStatus(P)));
    await renderApp({ path: `/printers/${P}`, info: CAL });
    const section = await screen.findByRole("region", { name: "Calibration" });
    expect(await within(section).findByText(/^Calibrated/)).toBeVisible();
    expect(within(section).getByText(/^Not calibrated/)).toBeVisible();
    const link = within(section).getByRole("link", { name: "Calibrate Main tray" });
    expect(link).toHaveAttribute("href", `/calibration?printer=${P}&tray=main`);
  });

  it("hides the calibration link from a print-scope user", async () => {
    mockApi(routes(pageStatus(P)));
    await renderApp({
      path: `/printers/${P}`,
      info: CAL,
      session: { signed_in: true, scope: "print", source: "api-key", user: null, bootstrap: false, csrf_token: "c" },
    });
    const section = await screen.findByRole("region", { name: "Calibration" });
    // The rows are in (the summary is read-only for this scope) before the missing link counts.
    expect(await within(section).findByText(/^Calibrated/)).toBeVisible();
    expect(screen.queryByRole("link", { name: /Calibrate/ })).toBeNull();
  });

  it("a printer that never answered shows no 'last status' (#206)", async () => {
    mockApi(routes(pageStatus(P, { online: null, printer_state: null, markers: [], trays: [], last_probe_age_s: 0 })));
    await renderApp({ path: `/printers/${P}` });
    const supplies = await screen.findByRole("region", { name: "Supplies" });
    expect(await within(supplies).findByText("No answer yet")).toBeVisible();
    expect(screen.queryByText(/Last status/)).toBeNull();
    expect(screen.getByText("Trays are listed once the printer has answered.")).toBeVisible();
  });

  it("a tape printer's detail is unchanged: Material panel, no supplies or trays", async () => {
    mockApi({
      [`GET /api/v1/printers/${PRINTER_A.id}`]: PRINTER_A,
      [`GET /api/v1/printers/${PRINTER_A.id}/status`]: status(PRINTER_A.id),
      [`GET /api/v1/printers/${PRINTER_A.id}/queue`]: [job("aaaaaaaa-0000-4000-8000-000000000009", PRINTER_A.id, "queued")],
    });
    await renderApp({ path: `/printers/${PRINTER_A.id}` });
    const material = await screen.findByRole("region", { name: "Material" });
    expect(await within(material).findByText("12 mm")).toBeVisible();
    expect(screen.queryByRole("region", { name: "Supplies" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Trays" })).toBeNull();
    expect(screen.getByText("Last status 4 s ago")).toBeVisible();
  });
});
