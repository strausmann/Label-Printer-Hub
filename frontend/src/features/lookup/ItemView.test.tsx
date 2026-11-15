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
    await userEvent.click(await screen.findByRole("button", { name: "Add to cart" }));
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
