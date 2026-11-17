// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderApp } from "../../test-utils";
import { mockApi, pngResponse, PRINTER_A, PRINTER_B, status } from "../test-api";
import { reloadCart } from "./cart";

beforeEach(() => {
  localStorage.clear();
  reloadCart();
});
afterEach(() => vi.unstubAllGlobals());

const DIE_CUT = { tape_loaded: "29mm", tape_width_mm: 29, media_kind: "die_cut", label_length_mm: 90, tape_colour: null };

const routes = (aStatus: Record<string, unknown>) => ({
  "GET /api/v1/lookup/snipeit/42": { app: "snipeit", id: "42", name: "Cordless drill", url: "https://assets.example.invalid/snipeit/42", extra: {} },
  "GET /api/v1/printers": [PRINTER_A, PRINTER_B],
  [`GET /api/v1/printers/${PRINTER_A.id}/status`]: status(PRINTER_A.id, aStatus),
  [`GET /api/v1/printers/${PRINTER_B.id}/status`]: status(PRINTER_B.id),
  "GET /api/v1/jobs": [],
  "POST /api/v1/render/preview": () => pngResponse(),
});

describe("the printer picker with a die-cut roll (#391)", () => {
  it("disables the printer in the list with the reason, and the print button with it", async () => {
    mockApi(routes(DIE_CUT));
    await renderApp({ path: "/asset/42" });
    const option = await screen.findByRole("option", { name: /Workshop PT-P750W.*Unsupported roll loaded: 29 × 90 mm die-cut labels/ });
    expect(option).toBeDisabled();
    expect(await screen.findByRole("button", { name: "Print now" })).toBeDisabled();
    expect(screen.getByText(/Printing on die-cut labels comes in a later version/)).toBeVisible();
  });

  it("the same printer with a continuous roll is selectable and prints (counter-check)", async () => {
    mockApi(routes({ ...DIE_CUT, media_kind: "continuous", label_length_mm: null }));
    await renderApp({ path: "/asset/42" });
    const option = await screen.findByRole("option", { name: /Workshop PT-P750W/ });
    expect(option).toBeEnabled();
    expect(await screen.findByRole("button", { name: "Print now" })).toBeEnabled();
  });

  it("names the reason in German", async () => {
    mockApi(routes(DIE_CUT));
    await renderApp({ path: "/asset/42", language: "de" });
    expect(await screen.findByRole("option", { name: /Nicht unterstützte Rolle eingelegt: 29 × 90 mm Stanzetiketten/ })).toBeDisabled();
  });

  it("the cart disables its print button too", async () => {
    localStorage.setItem("lph.cart", JSON.stringify([{ app: "snipeit", id: "42", name: "Cordless drill", content_type: "qr_two_lines", copies: 1 }]));
    reloadCart();
    mockApi({ ...routes(DIE_CUT), "POST /api/v1/print/check": [] });
    await renderApp({ path: "/cart" });
    const option = await screen.findByRole("option", { name: /Unsupported roll loaded/ });
    expect(option).toBeDisabled();
    expect(await screen.findByRole("button", { name: "Print 1 label" })).toBeDisabled();
  });
});
