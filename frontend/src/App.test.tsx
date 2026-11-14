// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderApp } from "./test-utils";

describe("App", () => {
  it("shows the overview page inside the shell for a signed-in user", async () => {
    await renderApp({ path: "/" });
    expect(screen.getByRole("heading", { level: 1, name: "Overview" })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Main" })).toBeInTheDocument();
  });

  it("shows sign-in, not the shell, when signed out", async () => {
    await renderApp({ path: "/", session: { signed_in: false, bootstrap: false } });
    expect(await screen.findByLabelText("API key")).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Main" })).toBeNull();
  });

  it("shows only the first-admin-key screen on a bootstrap session", async () => {
    await renderApp({
      path: "/",
      session: { signed_in: true, scope: "admin", source: "bootstrap", bootstrap: true, csrf_token: "c" },
    });
    expect(screen.getByRole("heading", { level: 1, name: "Create the first admin key" })).toBeInTheDocument();
    expect(screen.queryByRole("navigation")).toBeNull();
  });

  it("answers an unknown address with a way back", async () => {
    await renderApp({ path: "/no/such/page" });
    expect(screen.getByRole("heading", { level: 1, name: "Page not found" })).toBeInTheDocument();
  });

  it.each(["/printers/p1", "/jobs/j1", "/lookup/snipeit/42", "/loc/L1", "/asset/A1", "/spool/S1", "/product/P1", "/scan", "/settings/access"])(
    "has a route for %s",
    async (path) => {
      await renderApp({ path });
      expect(screen.getByRole("main")).toBeInTheDocument();
      expect(screen.queryByText("Page not found")).toBeNull();
    },
  );
});
