import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderApp, SIGNED_IN } from "../../test-utils";
import { job, mockApi, PRINTER_A, PRINTER_B, status } from "../test-api";

afterEach(() => vi.unstubAllGlobals());

const base = (jobs: unknown[] = []) => ({
  "GET /api/printers": [PRINTER_A, PRINTER_B],
  [`GET /api/printers/${PRINTER_A.id}/status`]: status(PRINTER_A.id),
  [`GET /api/printers/${PRINTER_B.id}/status`]: status(PRINTER_B.id, { tape_loaded: null }),
  "GET /api/jobs": jobs,
});

describe("Overview", () => {
  it("answers its three questions in order", async () => {
    mockApi(base());
    await renderApp({ path: "/" });
    const headings = await screen.findAllByRole("heading", { level: 2 });
    expect(headings.slice(0, 3).map((h) => h.textContent)).toEqual(["Printing now", "Needs attention", "Material"]);
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
    mockApi({ ...base(), "GET /api/printers": [PRINTER_A, { ...PRINTER_B, pause }] });
    await renderApp({ path: "/" });
    const section = await screen.findByRole("region", { name: "Needs attention" });
    expect(await within(section).findByText("Tape is empty")).toBeVisible();
    expect(within(section).getByText("Paused")).toBeVisible();
  });

  it("shows an unknown pause code verbatim", async () => {
    const pause = { source: "printer_error", reason_code: "flux_capacitor", since: "2026-11-04T10:00:00Z" };
    mockApi({ ...base(), "GET /api/printers": [PRINTER_A, { ...PRINTER_B, pause }] });
    await renderApp({ path: "/" });
    const section = await screen.findByRole("region", { name: "Needs attention" });
    const code = await within(section).findByText("flux_capacitor");
    expect(code.tagName).toBe("CODE");
  });

  it("says a manual pause was made by the user", async () => {
    const pause = { source: "user", reason_code: "user", since: "2026-11-04T10:00:00Z" };
    mockApi({ ...base(), "GET /api/printers": [PRINTER_A, { ...PRINTER_B, pause }] });
    await renderApp({ path: "/" });
    const section = await screen.findByRole("region", { name: "Needs attention" });
    expect(await within(section).findByText("Paused by user")).toBeVisible();
  });

  it("paused printer shows Resume", async () => {
    const { calls } = mockApi({ ...base(), [`POST /api/printers/${PRINTER_B.id}/resume`]: null });
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
    mockApi({ "GET /api/jobs": [] });
    await renderApp({ path: "/" });
    expect(await screen.findByText("The printers could not be loaded.")).toBeVisible();
  });

  describe("integration tiles (phone)", () => {
    const set = (snipeit: boolean, grocy: boolean, spoolman: boolean) => [
      { name: "snipeit" as const, configured: snipeit },
      { name: "grocy" as const, configured: grocy },
      { name: "spoolman" as const, configured: spoolman },
    ];

    it("shows a tile with the status for each configured integration, after the three questions", async () => {
      mockApi(base());
      await renderApp({ path: "/", info: { integrations: set(true, true, false) } });
      const section = await screen.findByRole("region", { name: "Integrations" });
      const snipe = within(section).getByRole("link", { name: /Snipe-IT/ });
      expect(snipe).toHaveAttribute("href", "/integrations/snipeit");
      expect(within(snipe).getByText("Connected")).toBeVisible();
      const headings = screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
      expect(headings.slice(0, 3)).toEqual(["Printing now", "Needs attention", "Material"]);
    });

    it("an admin gets Not set up with a Set up link for the rest", async () => {
      mockApi(base());
      await renderApp({ path: "/", info: { integrations: set(true, true, false) } });
      const section = await screen.findByRole("region", { name: "Integrations" });
      expect(within(section).getByText(/Spoolman/)).toBeVisible();
      expect(within(section).getByText(/Not set up/)).toBeVisible();
      expect(within(section).getByRole("link", { name: "Set up Spoolman" })).toHaveAttribute("href", "/settings/integrations");
    });

    it("a non-admin sees only what works; with nothing configured the section is gone", async () => {
      mockApi(base());
      await renderApp({ path: "/", info: { integrations: set(true, false, false) }, session: { ...SIGNED_IN, scope: "print" } });
      const section = await screen.findByRole("region", { name: "Integrations" });
      expect(within(section).queryByText(/Grocy/)).toBeNull();
      expect(within(section).getAllByRole("link")).toHaveLength(1);
    });

    it("no tiles and no heading when nothing is visible", async () => {
      mockApi(base());
      await renderApp({ path: "/", info: { integrations: set(false, false, false) }, session: { ...SIGNED_IN, scope: "read" } });
      await screen.findByRole("heading", { level: 2, name: "Printing now" });
      expect(screen.queryByRole("region", { name: "Integrations" })).toBeNull();
    });
  });
});
