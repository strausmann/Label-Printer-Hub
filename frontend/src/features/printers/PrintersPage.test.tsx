// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderApp } from "../../test-utils";
import { mockApi, PRINTER_A, PRINTER_B, status } from "../test-api";

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

  it("shows an empty state without printers", async () => {
    mockApi({ "GET /api/v1/printers": [] });
    await renderApp({ path: "/printers" });
    expect(await screen.findByText("No printers yet.")).toBeVisible();
  });
});
