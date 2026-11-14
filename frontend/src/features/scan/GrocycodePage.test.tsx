// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { act, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { knownBaseKey } from "../integrations/useKnownBase";
import { renderApp } from "../../test-utils";
import { lookupKey } from "../lookup/api";
import { mockApi } from "../test-api";

const GROCY = "https://grocy.example.invalid";

async function open(path: string, known = true, language: "en" | "de" = "en") {
  mockApi({});
  const app = await renderApp({ path: "/about", language });
  // A product opened earlier leaves its deep link in the cache; that is how the Grocy address is known.
  if (known) app.queryClient.setQueryData(lookupKey("grocy", "3"), { app: "grocy", id: "3", url: `${GROCY}/product/3` });
  await act(async () => {
    await app.router.navigate({ to: path });
  });
  return app;
}

beforeEach(() => localStorage.clear());
afterEach(() => vi.restoreAllMocks());

describe("the Grocycode page", () => {
  it("names a battery and links to it in Grocy when the Grocy address is known", async () => {
    await open("/grocycode/b/4");
    expect(await screen.findByRole("heading", { level: 1, name: "Grocy battery 4" })).toBeVisible();
    expect(await screen.findByRole("link", { name: /Open in Grocy/ })).toHaveAttribute("href", `${GROCY}/battery/4`);
  });

  it("links a chore to /chore/<id>", async () => {
    await open("/grocycode/c/7");
    expect(await screen.findByRole("heading", { level: 1, name: "Grocy chore 7" })).toBeVisible();
    expect(await screen.findByRole("link", { name: /Open in Grocy/ })).toHaveAttribute("href", `${GROCY}/chore/7`);
  });

  it("shows no link when the Grocy address is not known, and says what to do", async () => {
    await open("/grocycode/b/4", false);
    expect(await screen.findByRole("heading", { level: 1, name: "Grocy battery 4" })).toBeVisible();
    expect(screen.queryByRole("link", { name: /Open in Grocy/ })).toBeNull();
    expect(screen.getByText(/open it in Grocy/i)).toBeVisible();
  });

  it("offers to scan again", async () => {
    await open("/grocycode/b/4", false);
    expect(await screen.findByRole("link", { name: "Scan again" })).toHaveAttribute("href", "/scan");
  });

  it("is German in the German UI", async () => {
    await open("/grocycode/b/4", true, "de");
    expect(await screen.findByRole("heading", { level: 1, name: "Grocy-Batterie 4" })).toBeVisible();
  });

  it("an unknown kind is a not-found page", async () => {
    await open("/grocycode/p/4", false);
    expect(await screen.findByRole("heading", { name: /not found/i })).toBeVisible();
  });

  it("remembers the Grocy address across a reload", async () => {
    const first = await open("/grocycode/b/4");
    expect(await first.findByRole("link", { name: /Open in Grocy/ })).toBeVisible();
    first.unmount();
    // A fresh query cache, as after a reload: only the stored address is left.
    await open("/grocycode/b/4", false);
    expect(await screen.findByRole("link", { name: /Open in Grocy/ })).toHaveAttribute("href", `${GROCY}/battery/4`);
  });

  it("works without storage: a hint, no crash", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    await open("/grocycode/b/4", false);
    expect(await screen.findByRole("heading", { level: 1, name: "Grocy battery 4" })).toBeVisible();
    expect(screen.queryByRole("link", { name: /Open in Grocy/ })).toBeNull();
  });

  it.each(["javascript:alert(1)", "data:text/html,x", "not a url", `${GROCY}`.replace("https", "ftp")])(
    "does not trust a stored %j",
    async (value) => {
      localStorage.setItem(knownBaseKey("grocy"), value);
      await open("/grocycode/b/4", false);
      expect(await screen.findByRole("heading", { level: 1, name: "Grocy battery 4" })).toBeVisible();
      expect(screen.queryByRole("link", { name: /Open in Grocy/ })).toBeNull();
    },
  );
});
