import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderApp, SIGNED_IN } from "../../test-utils";
import { job, mockApi, PAGE_PRINTER, PRINTER_A, PRINTER_B, pageStatus, status } from "../test-api";

afterEach(() => vi.unstubAllGlobals());

const base = (jobs: unknown[] = []) => ({
  "GET /api/v1/printers": [PRINTER_A, PRINTER_B],
  [`GET /api/v1/printers/${PRINTER_A.id}/status`]: status(PRINTER_A.id),
  [`GET /api/v1/printers/${PRINTER_B.id}/status`]: status(PRINTER_B.id, { tape_loaded: null }),
  "GET /api/v1/jobs": jobs,
});

describe("Overview", () => {
  it("answers its three questions in order", async () => {
    mockApi(base());
    await renderApp({ path: "/" });
    const headings = await screen.findAllByRole("heading", { level: 2 });
    // The phone-only Integrations and Sheets tiles sit between the second and third question.
    const questions = headings.map((h) => h.textContent).filter((h) => h !== "Integrations" && h !== "Sheets");
    expect(questions.slice(0, 3)).toEqual(["Printing now", "Needs attention", "Material"]);
  });

  it("links to the sheet archive and the calibration when their features are on, for every scope", async () => {
    mockApi(base());
    for (const scope of ["read", "print", "admin"] as const) {
      const { unmount } = await renderApp({
        path: "/",
        info: { features: { sheets: true, calibration: true } },
        session: { ...SIGNED_IN, scope },
      });
      const group = await screen.findByRole("region", { name: "Sheets" });
      expect(within(group).getByRole("link", { name: "Sheet archive" })).toHaveAttribute("href", "/sheets/archive");
      expect(within(group).getByRole("link", { name: "Calibration" })).toHaveAttribute("href", "/calibration");
      unmount();
    }
  });

  it("shows each entry only while its own feature is on", async () => {
    mockApi(base());
    const only = async (features: Record<string, boolean>) => {
      const { unmount } = await renderApp({ path: "/", info: { features } });
      await screen.findByRole("heading", { level: 2, name: "Printing now" });
      // The sidebar carries the same names; the entries of the Overview are the ones in its own group.
      const group = screen.queryByRole("region", { name: "Sheets" });
      const names = group ? within(group).getAllByRole("link").map((l) => l.textContent) : [];
      unmount();
      return names;
    };
    expect(await only({ sheets: true, calibration: false })).toContain("Sheet archive");
    expect(await only({ sheets: true, calibration: false })).not.toContain("Calibration");
    expect(await only({ sheets: false, calibration: true })).toContain("Calibration");
    expect(await only({ sheets: false, calibration: true })).not.toContain("Sheet archive");
    expect(await only({ sheets: false, calibration: false })).toEqual([]);
  });

  it("lists a running job under Printing now", async () => {
    mockApi(base([job("aaaaaaaa-0000-4000-8000-000000000001", PRINTER_A.id, "printing", { template_key: "spool-label" })]));
    await renderApp({ path: "/" });
    const section = (await screen.findByRole("region", { name: "Printing now" }));
    expect(await within(section).findByText(/spool-label/)).toBeVisible();
    expect(within(section).getByText(/Workshop PT-P750W/)).toBeVisible();
  });

  it("lists a failed job under Needs attention with its reason", async () => {
    mockApi(
      base([job("aaaaaaaa-0000-4000-8000-000000000002", PRINTER_A.id, "failed", { error: "Cover open during print" })]),
    );
    await renderApp({ path: "/" });
    const section = await screen.findByRole("region", { name: "Needs attention" });
    expect(await within(section).findByText("Cover open during print")).toBeVisible();
    expect(within(section).getByText("Failed")).toBeVisible();
  });

  it("ignores failures older than a day", async () => {
    const old = "2026-01-01T00:00:00Z";
    mockApi(base([job("aaaaaaaa-0000-4000-8000-000000000003", PRINTER_A.id, "failed", { error: "Old jam", updated_at: old })]));
    await renderApp({ path: "/" });
    const section = await screen.findByRole("region", { name: "Needs attention" });
    await within(section).findByText("Office QL-820NWB");
    expect(within(section).queryByText("Old jam")).toBeNull();
  });

  it("shows why a printer was paused automatically", async () => {
    const pause = { source: "printer_error", reason_code: "tape_empty", since: "2026-11-04T10:00:00Z" };
    mockApi({ ...base(), "GET /api/v1/printers": [PRINTER_A, { ...PRINTER_B, pause }] });
    await renderApp({ path: "/" });
    const section = await screen.findByRole("region", { name: "Needs attention" });
    expect(await within(section).findByText("Tape is empty")).toBeVisible();
    expect(within(section).getByText("Paused")).toBeVisible();
  });

  it("shows an unknown pause code verbatim", async () => {
    const pause = { source: "printer_error", reason_code: "flux_capacitor", since: "2026-11-04T10:00:00Z" };
    mockApi({ ...base(), "GET /api/v1/printers": [PRINTER_A, { ...PRINTER_B, pause }] });
    await renderApp({ path: "/" });
    const section = await screen.findByRole("region", { name: "Needs attention" });
    const code = await within(section).findByText("flux_capacitor");
    expect(code.tagName).toBe("CODE");
  });

  it("says a manual pause was made by the user", async () => {
    const pause = { source: "user", reason_code: "user", since: "2026-11-04T10:00:00Z" };
    mockApi({ ...base(), "GET /api/v1/printers": [PRINTER_A, { ...PRINTER_B, pause }] });
    await renderApp({ path: "/" });
    const section = await screen.findByRole("region", { name: "Needs attention" });
    expect(await within(section).findByText("Paused by user")).toBeVisible();
  });

  it("paused printer shows Resume", async () => {
    const { calls } = mockApi({ ...base(), [`POST /api/v1/printers/${PRINTER_B.id}/resume`]: null });
    await renderApp({ path: "/" });
    const section = await screen.findByRole("region", { name: "Needs attention" });
    expect(await within(section).findByText("Office QL-820NWB")).toBeVisible();
    expect(within(section).getByText("Paused")).toBeVisible();
    await userEvent.click(within(section).getByRole("button", { name: "Resume Office QL-820NWB" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path.endsWith("/resume"))).toBe(true));
  });

  it("shows tape per printer: width, colour swatch with its name, and the empty state", async () => {
    mockApi(base());
    await renderApp({ path: "/" });
    const material = await screen.findByRole("region", { name: "Material" });
    const a = (await within(material).findByText("Workshop PT-P750W")).closest("li")!;
    expect(within(a).getByText("12 mm")).toBeVisible();
    expect(within(a).getByText("Blue")).toBeVisible();
    const b = within(material).getByText("Office QL-820NWB").closest("li")!;
    expect(within(b).getByText("No tape loaded")).toBeVisible();
  });

  it("shows printer cards linking to the detail page", async () => {
    mockApi(base());
    await renderApp({ path: "/" });
    const link = await screen.findByRole("link", { name: /Workshop PT-P750W/ });
    expect(link).toHaveAttribute("href", `/printers/${PRINTER_A.id}`);
  });

  it("says so when the printers cannot be loaded", async () => {
    mockApi({ "GET /api/v1/jobs": [] });
    await renderApp({ path: "/" });
    expect(await screen.findByText("The printers could not be loaded.")).toBeVisible();
  });

  describe("integration tiles (phone)", () => {
    const set = (snipeit: boolean, grocy: boolean, spoolman: boolean) => [
      { name: "snipeit" as const, configured: snipeit },
      { name: "grocy" as const, configured: grocy },
      { name: "spoolman" as const, configured: spoolman },
    ];

    it("shows a tile with the status for each configured integration, directly after Needs attention and before Material", async () => {
      mockApi(base());
      await renderApp({ path: "/", info: { integrations: set(true, true, false) } });
      const section = await screen.findByRole("region", { name: "Integrations" });
      const snipe = within(section).getByRole("link", { name: /Snipe-IT/ });
      expect(snipe).toHaveAttribute("href", "/integrations/snipeit");
      expect(within(snipe).getByText("Configured")).toBeVisible();
      expect(within(snipe).queryByText("Connected")).toBeNull();
      const headings = screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
      expect(headings.slice(0, 4)).toEqual(["Printing now", "Needs attention", "Integrations", "Material"]);
    });

    it("an admin sees no tile for an integration that is not set up", async () => {
      mockApi(base());
      await renderApp({ path: "/", info: { integrations: set(true, true, false) } });
      const section = await screen.findByRole("region", { name: "Integrations" });
      expect(within(section).queryByText(/Spoolman/)).toBeNull();
      expect(within(section).queryByText(/Not set up/)).toBeNull();
      expect(within(section).queryByRole("link", { name: /Set up/ })).toBeNull();
      expect(within(section).getAllByRole("link")).toHaveLength(2);
    });

    it("with nothing configured even an admin gets no section", async () => {
      mockApi(base());
      await renderApp({ path: "/", info: { integrations: set(false, false, false) } });
      await screen.findByRole("heading", { level: 2, name: "Printing now" });
      expect(screen.queryByRole("region", { name: "Integrations" })).toBeNull();
    });

    it("no tiles and no heading when nothing is visible", async () => {
      mockApi(base());
      await renderApp({ path: "/", info: { integrations: set(false, false, false) }, session: { ...SIGNED_IN, scope: "read" } });
      await screen.findByRole("heading", { level: 2, name: "Printing now" });
      expect(screen.queryByRole("region", { name: "Integrations" })).toBeNull();
    });
  });

  describe("page printers", () => {
    const withPage = (pageStat: Record<string, unknown>) => ({
      ...base(),
      "GET /api/v1/printers": [PRINTER_A, PAGE_PRINTER],
      [`GET /api/v1/printers/${PAGE_PRINTER.id}/status`]: pageStat,
    });
    const lowBlack = { name: "Black toner", color: "#000000", level_percent: 4, low: true, empty: false, some_remaining: false, type: "toner" };

    it("counts a printer with a low toner as running out of material", async () => {
      mockApi(withPage(pageStatus(PAGE_PRINTER.id, { markers: [lowBlack] })));
      await renderApp({ path: "/" });
      const section = await screen.findByRole("region", { name: "Material" });
      expect(await within(section).findByText("1 printer is running out of material")).toBeVisible();
      expect(within(section).getByText("4 %, low")).toBeVisible();
    });

    it("says nothing about running out while the toner is fine", async () => {
      mockApi(withPage(pageStatus(PAGE_PRINTER.id)));
      await renderApp({ path: "/" });
      const section = await screen.findByRole("region", { name: "Material" });
      expect(await within(section).findByText("Black toner")).toBeVisible();
      expect(within(section).queryByText(/running out/)).toBeNull();
    });

    it("a stopped page printer needs attention, with the reason in words", async () => {
      const stopped = pageStatus(PAGE_PRINTER.id, {
        printer_state: "stopped",
        state_reasons: [{ keyword: "toner-empty", severity: "error", blocking: true }],
      });
      mockApi(withPage(stopped));
      await renderApp({ path: "/" });
      const section = await screen.findByRole("region", { name: "Needs attention" });
      expect(await within(section).findByText("Stopped")).toBeVisible();
      expect(within(section).getByText("toner empty")).toBeVisible();
    });

    it("a printer that never answered shows 'No answer yet' under Material", async () => {
      mockApi(withPage(pageStatus(PAGE_PRINTER.id, { online: null, printer_state: null, markers: [], trays: [] })));
      await renderApp({ path: "/" });
      const section = await screen.findByRole("region", { name: "Material" });
      expect(await within(section).findByText("No answer yet")).toBeVisible();
    });

    it("tape printers keep their material row", async () => {
      mockApi(withPage(pageStatus(PAGE_PRINTER.id)));
      await renderApp({ path: "/" });
      const section = await screen.findByRole("region", { name: "Material" });
      expect(await within(section).findByText("Blue")).toBeVisible();
    });
  });
});
