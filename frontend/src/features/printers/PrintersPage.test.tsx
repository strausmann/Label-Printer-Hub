// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderApp } from "../../test-utils";
import { job, mockApi, PRINTER_A, PRINTER_B, status } from "../test-api";

afterEach(() => vi.unstubAllGlobals());

describe("Printers", () => {
  it("lists every printer with a state word, tape width and swatch name", async () => {
    mockApi({
      "GET /api/v1/printers": [PRINTER_A, PRINTER_B],
      [`GET /api/v1/printers/${PRINTER_A.id}/status`]: status(PRINTER_A.id),
      [`GET /api/v1/printers/${PRINTER_B.id}/status`]: status(PRINTER_B.id, { online: false }),
    });
    await renderApp({ path: "/printers" });
    expect(await screen.findByRole("heading", { level: 1, name: "Printers" })).toBeVisible();
    expect(await screen.findByText("Ready")).toBeVisible();
    // The paused flag wins over the probe result: the badge says what the operator can act on.
    expect(screen.getByText("Paused")).toBeVisible();
    expect(screen.getAllByText("Blue")[0]).toBeVisible();
  });

  it("the card agrees with the entry (#376)", async () => {
    // An open cover while a job waits: the card says Problem, as the notification does.
    mockApi({
      "GET /api/v1/printers": [PRINTER_A],
      [`GET /api/v1/printers/${PRINTER_A.id}/status`]: status(PRINTER_A.id, { error_flags: ["doorOpen"], error_state: "doorOpen" }),
      "GET /api/v1/jobs": [job("aaaaaaaa-0000-4000-8000-000000000001", PRINTER_A.id, "queued")],
    });
    await renderApp({ path: "/printers" });
    const card = await screen.findByRole("link", { name: /Workshop PT-P750W/ });
    expect(await within(card).findByText("Problem")).toBeVisible();
    expect(within(card).getByText("Cover open — close it to print")).toBeVisible();
    expect(card.textContent).not.toContain("doorOpen");
  });

  it("an open cover with nothing waiting is a warning on the card", async () => {
    mockApi({
      "GET /api/v1/printers": [PRINTER_A],
      [`GET /api/v1/printers/${PRINTER_A.id}/status`]: status(PRINTER_A.id, { error_flags: ["doorOpen"], error_state: "doorOpen" }),
      "GET /api/v1/jobs": [],
    });
    await renderApp({ path: "/printers" });
    const card = await screen.findByRole("link", { name: /Workshop PT-P750W/ });
    expect(await within(card).findByText("Warning")).toBeVisible();
  });

  it("shows an empty state without printers", async () => {
    mockApi({ "GET /api/v1/printers": [] });
    await renderApp({ path: "/printers" });
    expect(await screen.findByText("No printers yet.")).toBeVisible();
  });
});
