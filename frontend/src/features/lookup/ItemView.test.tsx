// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderApp } from "../../test-utils";
import { mockApi, pngResponse, PRINTER_A, PRINTER_B, respond, status } from "../test-api";
import { CART_KEY, reloadCart } from "./cart";

beforeEach(() => {
  localStorage.clear();
  reloadCart();
});
afterEach(() => vi.unstubAllGlobals());

const BATCH = "cccccccc-0000-4000-8000-000000000001";
const item = (app: string, id: string, over: Record<string, unknown> = {}) => ({
  app,
  id,
  name: "Cordless drill",
  url: `https://assets.example.invalid/${app}/${id}`,
  extra: {},
  ...over,
});

function routes(app = "snipeit", id = "42", extra: Record<string, unknown> = {}) {
  return {
    [`GET /api/v1/lookup/${app}/${id}`]: item(app, id),
    "GET /api/v1/printers": [PRINTER_A, PRINTER_B],
    [`GET /api/v1/printers/${PRINTER_A.id}/status`]: status(PRINTER_A.id),
    "POST /api/v1/render/preview": () => pngResponse(),
    [`POST /api/v1/print/${PRINTER_A.id}/batch`]: { batch_id: BATCH, printer_id: PRINTER_A.id, queued_at: "2026-11-04T10:00:00Z", job_ids: ["jjjjjjjj-0000-4000-8000-000000000001"] },
    ...extra,
  };
}

describe("ItemView", () => {
  it("503 integration_not_configured links to settings", async () => {
    mockApi({
      "GET /api/v1/lookup/snipeit/42": respond(503, { type: "integration_not_configured", title: "Service Unavailable", detail: "Snipe-IT is not configured" }),
    });
    await renderApp({ path: "/asset/42" });
    expect(await screen.findByText(/Snipe-IT is not set up yet/)).toBeVisible();
    expect(screen.getByRole("link", { name: "Open Settings › Integrations" })).toHaveAttribute("href", "/settings/integrations");
  });

  it("an unknown item reads Not found in the app, with the id in the mono font", async () => {
    mockApi({ "GET /api/v1/lookup/spoolman/9": respond(404, { type: "about:blank", title: "Not Found", detail: "spool 9 not found" }) });
    await renderApp({ path: "/spool/9" });
    expect(await screen.findByRole("heading", { level: 1, name: "Not found in Spoolman" })).toBeVisible();
    const id = screen.getByText("9");
    expect(id.tagName).toBe("CODE");
  });

  it.each([
    ["/asset/42", "snipeit", "42"],
    ["/loc/5", "snipeit", "loc%3A5"],
    ["/spool/7", "spoolman", "7"],
    ["/product/3", "grocy", "3"],
    ["/lookup/grocy/11", "grocy", "11"],
  ])("%s asks the %s integration for %s", async (path, app, id) => {
    const { calls } = mockApi(routes(app, id));
    await renderApp({ path });
    await screen.findByRole("heading", { level: 1, name: "Cordless drill" });
    expect(calls.some((c) => c.path === `/api/v1/lookup/${app}/${id}`)).toBe(true);
  });

  it("asks for no printer status while no printer is selected", async () => {
    const { calls } = mockApi(routes("snipeit", "42", { "GET /api/v1/printers": [] }));
    await renderApp({ path: "/asset/42" });
    await screen.findByRole("heading", { level: 1, name: "Cordless drill" });
    expect(calls.filter((c) => /\/printers\/\/status/.test(c.path))).toEqual([]);
  });

  it("shows the item, a link to its source app, the preview and the printer picker", async () => {
    const { calls } = mockApi(routes());
    await renderApp({ path: "/asset/42" });
    await screen.findByRole("heading", { level: 1, name: "Cordless drill" });
    expect(screen.getByRole("link", { name: "Open in Snipe-IT" })).toHaveAttribute("href", "https://assets.example.invalid/snipeit/42");
    expect(await screen.findByRole("img", { name: "Label preview" })).toBeVisible();
    const picker = screen.getByRole("combobox", { name: "Printer" });
    expect(within(picker).getAllByRole("option").map((o) => o.textContent)).toEqual(["Workshop PT-P750W · Tape printer · Ready", "Office QL-820NWB · Tape printer"]);
    const preview = calls.find((c) => c.path === "/api/v1/render/preview")!;
    expect(JSON.parse(preview.body!)).toMatchObject({ content_type: "qr_two_lines", tape_mm: 12, data: { title: "Cordless drill", primary_id: "42" } });
  });

  it("does not turn a script URL from the integration into a link", async () => {
    mockApi(routes("snipeit", "42", { "GET /api/v1/lookup/snipeit/42": item("snipeit", "42", { url: "javascript:alert(1)" }) }));
    await renderApp({ path: "/asset/42" });
    await screen.findByRole("heading", { level: 1, name: "Cordless drill" });
    expect(screen.queryByRole("link", { name: "Open in Snipe-IT" })).toBeNull();
  });

  it("a failing preview does not block printing", async () => {
    mockApi(routes("snipeit", "42", { "POST /api/v1/render/preview": respond(409, { error_code: "unsupported_tape", error_message: "x" }) }));
    await renderApp({ path: "/asset/42" });
    expect(await screen.findByText("No preview for this tape.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Print now" })).toBeEnabled();
  });

  it("Print now sends one lookup item to the chosen printer and links to the job", async () => {
    const { calls } = mockApi(routes());
    await renderApp({ path: "/asset/42" });
    await screen.findByRole("img", { name: "Label preview" });
    await userEvent.click(screen.getByRole("button", { name: "Print now" }));
    expect(await screen.findByText(/Sent to Workshop PT-P750W/)).toBeVisible();
    const post = calls.find((c) => c.path === `/api/v1/print/${PRINTER_A.id}/batch`)!;
    expect(JSON.parse(post.body!)).toEqual({
      items: [{ content_type: "qr_two_lines", options: { copies: 1 }, lookup: { app: "snipeit", identifier: "42" } }],
    });
    expect(screen.getByRole("link", { name: "View the job" })).toHaveAttribute("href", "/jobs/jjjjjjjj-0000-4000-8000-000000000001");
  });

  it("shows why printing was refused", async () => {
    mockApi(routes("snipeit", "42", { [`POST /api/v1/print/${PRINTER_A.id}/batch`]: respond(409, { detail: { error_code: "printer_offline", error_message: "The printer is offline." } }) }));
    await renderApp({ path: "/asset/42" });
    await userEvent.click(await screen.findByRole("button", { name: "Print now" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The printer is offline.");
  });

  it("Add to cart stores the item and shows the cart link", async () => {
    mockApi(routes());
    await renderApp({ path: "/asset/42" });
    await userEvent.click(within(await screen.findByRole("region", { name: "Print" })).getByRole("button", { name: "Add to cart" }));
    expect(JSON.parse(localStorage.getItem(CART_KEY)!)).toEqual([
      { app: "snipeit", id: "42", name: "Cordless drill", content_type: "qr_two_lines", copies: 1 },
    ]);
    expect(await screen.findByRole("link", { name: "Cart (1)" })).toHaveAttribute("href", "/cart");
  });

  it("remembers the printer the person picked", async () => {
    mockApi(routes());
    await renderApp({ path: "/asset/42" });
    await screen.findByRole("option", { name: /Office QL-820NWB/ });
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Printer" }), PRINTER_B.id);
    await waitFor(() => expect(localStorage.getItem("lph.printer")).toBe(PRINTER_B.id));
  });
});

describe("the spool label of a Spoolman item (#346)", () => {
  const SWATCH = { spool_id: 7, language: "en", vendor: "TecBears", title: "PETG", color_name: "Orange", color_hexes: ["FF5F00"] };
  const spool = (swatch: Record<string, unknown> = SWATCH) => ({
    app: "spoolman",
    id: "7",
    name: "TecBears Orange",
    url: "https://spoolman.example.invalid/spool/show/7",
    extra: { secondary: ["640g remaining"], swatch },
  });
  const QL = (layout_defaults: Record<string, unknown> = {}) => ({ ...PRINTER_B, paused: false, layout_defaults });
  function spoolRoutes(over: Record<string, unknown> = {}) {
    return {
      "GET /api/v1/lookup/spoolman/7": spool(),
      "GET /api/v1/printers": [PRINTER_A, QL()],
      [`GET /api/v1/printers/${PRINTER_A.id}/status`]: status(PRINTER_A.id),
      [`GET /api/v1/printers/${PRINTER_B.id}/status`]: status(PRINTER_B.id, { tape_loaded: "62mm", tape_width_mm: 62 }),
      "POST /api/v1/render/preview": () => pngResponse(),
      [`POST /api/v1/print/${PRINTER_B.id}/batch`]: { batch_id: BATCH, printer_id: PRINTER_B.id, queued_at: "x", job_ids: ["j"] },
      ...over,
    };
  }
  const previews = (calls: { path: string; body?: string | null }[]) =>
    calls.filter((c) => c.path === "/api/v1/render/preview").map((c) => JSON.parse(c.body!) as Record<string, unknown>);
  beforeEach(() => localStorage.setItem("lph.printer", PRINTER_B.id));

  it("a Spoolman item previews the spool label with its swatch", async () => {
    const { calls } = mockApi(spoolRoutes());
    await renderApp({ path: "/spool/7" });
    await screen.findByRole("img", { name: "Label preview" });
    const body = previews(calls).at(-1)!;
    expect(body).toMatchObject({ content_type: "spool_swatch", tape_mm: 62, data: { swatch: SWATCH, qr_payload: "https://spoolman.example.invalid/spool/show/7" } });
    expect(screen.getByRole("combobox", { name: "Layout" })).toHaveValue("spool_swatch");
  });

  it("a stored along default does not reach the swatch preview", async () => {
    const { calls } = mockApi(spoolRoutes({ "GET /api/v1/printers": [PRINTER_A, QL({ "62": { orientation: "along", preset: null } })] }));
    await renderApp({ path: "/spool/7" });
    await screen.findByRole("img", { name: "Label preview" });
    for (const body of previews(calls)) {
      expect(body).not.toHaveProperty("orientation");
      expect(body).not.toHaveProperty("layout_preset");
    }
    await userEvent.click(screen.getByRole("button", { name: "Print now" }));
    await screen.findByText(/Sent to Office QL-820NWB/);
    const post = calls.find((c) => c.path === `/api/v1/print/${PRINTER_B.id}/batch`)!;
    expect(JSON.parse(post.body!)).toEqual({
      items: [{ content_type: "spool_swatch", options: { copies: 1 }, lookup: { app: "spoolman", identifier: "7" } }],
    });
  });

  it("the layout picker is hidden for the spool label", async () => {
    mockApi(spoolRoutes());
    await renderApp({ path: "/spool/7" });
    await screen.findByRole("img", { name: "Label preview" });
    expect(screen.queryByRole("radiogroup", { name: "Direction" })).toBeNull();
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Layout" }), "qr_two_lines");
    expect(await screen.findByRole("radiogroup", { name: "Direction" })).toBeVisible();
  });

  it("a changed swatch asks for a new preview", async () => {
    const lookup = { current: spool() };
    const { calls } = mockApi(spoolRoutes({ "GET /api/v1/lookup/spoolman/7": () => new Response(JSON.stringify(lookup.current), { headers: { "content-type": "application/json" } }) }));
    const { queryClient } = await renderApp({ path: "/spool/7" });
    await screen.findByRole("img", { name: "Label preview" });
    const before = previews(calls).length;
    lookup.current = spool({ ...SWATCH, color_name: "Grey" });
    await queryClient.invalidateQueries({ queryKey: ["lookup"] });
    await waitFor(() => expect(previews(calls).length).toBeGreaterThan(before));
    expect(previews(calls).at(-1)).toMatchObject({ data: { swatch: { color_name: "Grey" } } });
  });

  it("a tape without 62 mm shows the not-available message", async () => {
    mockApi(
      spoolRoutes({
        [`GET /api/v1/printers/${PRINTER_B.id}/status`]: status(PRINTER_B.id, { tape_loaded: "29mm", tape_width_mm: 29 }),
        "POST /api/v1/render/preview": respond(409, { error_code: "unsupported_tape", error_message: "x" }),
      }),
    );
    await renderApp({ path: "/spool/7" });
    expect(await screen.findByText("No preview for this tape.")).toBeVisible();
  });

  it("the content type label reads Spool label", async () => {
    mockApi(spoolRoutes());
    await renderApp({ path: "/spool/7" });
    const select = await screen.findByRole("combobox", { name: "Layout" });
    expect(within(select).getAllByRole("option")[0]).toHaveTextContent("Spool label");
  });

  it("the content type label reads Spulenetikett in German", async () => {
    mockApi(spoolRoutes());
    await renderApp({ path: "/spool/7", language: "de" });
    const select = await screen.findByRole("combobox", { name: "Layout" });
    expect(within(select).getAllByRole("option")[0]).toHaveTextContent("Spulenetikett");
  });
});
