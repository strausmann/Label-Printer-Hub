// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { act, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderApp } from "../../test-utils";
import { lookupKey } from "../lookup/api";
import { knownBaseKey } from "../integrations/useKnownBase";
import { apiErrorBody, mockApi } from "../test-api";

const GROCY = "https://grocy.example.invalid";

const BATTERY = {
  id: "4",
  name: "Remote AAA",
  description: "Warranty ends 2027",
  url: `${GROCY}/battery/4`,
  last_charged: "2026-03-13T18:12:28",
  next_estimated_charge: null,
  charge_cycles: 4,
};
const CHORE = {
  id: "7",
  name: "Water the plants",
  description: null,
  url: `${GROCY}/chore/7`,
  last_tracked: "2026-11-10T09:30:00",
  next_estimated_execution: "2026-11-17T09:30:00",
  assigned_to: "Anna B.",
};
const B = "GET /api/v1/lookup/grocy/batteries/4";
const C = "GET /api/v1/lookup/grocy/chores/7";

beforeEach(() => localStorage.clear());
afterEach(() => vi.restoreAllMocks());

/** Opens a path inside the app; `known` leaves a product's deep link in the cache, as an earlier lookup would. */
async function open(path: string, routes: Record<string, unknown>, known = false, language: "en" | "de" = "en") {
  const api = mockApi(routes);
  const app = await renderApp({ path: "/about", language });
  if (known) app.queryClient.setQueryData(lookupKey("grocy", "3"), { app: "grocy", id: "3", url: `${GROCY}/product/3` });
  await act(async () => {
    await app.router.navigate({ to: path });
  });
  return { ...app, ...api };
}

describe("the Grocycode page, battery", () => {
  it("shows the battery's name, description and facts, and links to it in Grocy", async () => {
    await open("/grocycode/b/4", { [B]: BATTERY });
    expect(await screen.findByRole("heading", { level: 1, name: "Remote AAA" })).toBeVisible();
    expect(screen.getByText("Grocy battery 4")).toBeVisible();
    expect(screen.getByText("Warranty ends 2027")).toBeVisible();
    const facts = screen.getByText("Last charged").closest("dl")!;
    expect(within(facts).getByText("Charge cycles").nextSibling).toHaveTextContent("4");
    expect(within(facts).getByText("Last charged").nextSibling).toHaveTextContent(/2026/);
    // Never charged again is said in words, not left empty.
    expect(within(facts).getByText("Next charge").nextSibling).toHaveTextContent("Never");
    // The link comes with the answer: no earlier product lookup is needed.
    expect(screen.getByRole("link", { name: /Open in Grocy/ })).toHaveAttribute("href", `${GROCY}/battery/4`);
    expect(screen.getByRole("link", { name: "Scan again" })).toHaveAttribute("href", "/scan");
  });

  it("says Never for a battery that was never charged", async () => {
    await open("/grocycode/b/4", { [B]: { ...BATTERY, last_charged: null, charge_cycles: 0 } });
    await screen.findByRole("heading", { level: 1, name: "Remote AAA" });
    expect(screen.getByText("Last charged").nextSibling).toHaveTextContent("Never");
  });

  it("an unknown battery says so and offers no Grocy link", async () => {
    await open("/grocycode/b/4", { [B]: new Response(JSON.stringify({ status: 404 }), { status: 404 }) }, true);
    expect(await screen.findByRole("heading", { level: 1, name: "Not found in Grocy" })).toBeVisible();
    expect(screen.getByText("Grocy has no battery with the ID 4.")).toBeVisible();
    expect(screen.queryByRole("link", { name: /Open in Grocy/ })).toBeNull();
    expect(screen.getByRole("link", { name: "Scan again" })).toBeVisible();
  });

  it("a Grocy that is not set up is explained, with the way to Settings", async () => {
    await open("/grocycode/b/4", {
      [B]: new Response(JSON.stringify(apiErrorBody("integration_not_configured", "Grocy is not configured")), {
        status: 503,
        headers: { "Content-Type": "application/json" },
      }),
    });
    expect(await screen.findByText("Grocy is not set up yet, so this cannot be shown.")).toBeVisible();
    expect(screen.getByRole("link", { name: /Open Settings/ })).toBeVisible();
  });

  it("another failure is an alert with a retry that asks again", async () => {
    let calls = 0;
    const { fetchMock } = await open("/grocycode/b/4", {
      [B]: () => (++calls === 1 ? new Response("{}", { status: 502 }) : BATTERY),
    });
    expect(await screen.findByRole("alert")).toHaveTextContent("The details could not be loaded.");
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Remote AAA" })).toBeVisible();
    expect(fetchMock.mock.calls.filter(([u]) => String(u).includes("/batteries/4")).length).toBe(2);
  });

  it("while loading, the page says what was scanned and that it is loading", async () => {
    await open("/grocycode/b/4", { [B]: () => new Promise<never>(() => {}) });
    expect(await screen.findByRole("status")).toHaveTextContent("Loading…");
    expect(screen.getByRole("heading", { level: 1, name: "Grocy battery 4" })).toBeVisible();
  });

  it("without the answer's link, the address seen earlier still links (loading, no stored data)", async () => {
    await open("/grocycode/b/4", { [B]: () => new Promise<never>(() => {}) }, true);
    expect(await screen.findByRole("link", { name: /Open in Grocy/ })).toHaveAttribute("href", `${GROCY}/battery/4`);
  });

  it("an answer whose link is not a web link gives no link", async () => {
    await open("/grocycode/b/4", { [B]: { ...BATTERY, url: "javascript:alert(1)" } });
    await screen.findByRole("heading", { level: 1, name: "Remote AAA" });
    expect(screen.queryByRole("link", { name: /Open in Grocy/ })).toBeNull();
  });

  it("works with storage that throws", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    await open("/grocycode/b/4", { [B]: { ...BATTERY, url: null } });
    expect(await screen.findByRole("heading", { level: 1, name: "Remote AAA" })).toBeVisible();
    expect(screen.queryByRole("link", { name: /Open in Grocy/ })).toBeNull();
  });

  it.each(["javascript:alert(1)", "data:text/html,x", "not a url"])("does not trust a stored %j", async (value) => {
    localStorage.setItem(knownBaseKey("grocy"), value);
    await open("/grocycode/b/4", { [B]: { ...BATTERY, url: null } });
    await screen.findByRole("heading", { level: 1, name: "Remote AAA" });
    expect(screen.queryByRole("link", { name: /Open in Grocy/ })).toBeNull();
  });

  it("remembers the Grocy address across a reload when the answer carries none", async () => {
    const first = await open("/grocycode/b/4", { [B]: { ...BATTERY, url: null } }, true);
    expect(await first.findByRole("link", { name: /Open in Grocy/ })).toBeVisible();
    first.unmount();
    await open("/grocycode/b/4", { [B]: { ...BATTERY, url: null } });
    expect(await screen.findByRole("link", { name: /Open in Grocy/ })).toHaveAttribute("href", `${GROCY}/battery/4`);
  });

  it("is German in the German UI, dates in German", async () => {
    await open("/grocycode/b/4", { [B]: BATTERY }, false, "de");
    expect(await screen.findByRole("heading", { level: 1, name: "Remote AAA" })).toBeVisible();
    expect(screen.getByText("Grocy-Batterie 4")).toBeVisible();
    expect(screen.getByText("Zuletzt geladen")).toBeVisible();
    expect(screen.getByText("Zuletzt geladen").nextSibling).toHaveTextContent(/13\.03\.2026/);
    expect(screen.getByText("Nächste Ladung").nextSibling).toHaveTextContent("Nie");
  });
});

describe("the Grocycode page, chore", () => {
  it("shows the chore's facts including who it is assigned to", async () => {
    await open("/grocycode/c/7", { [C]: CHORE });
    expect(await screen.findByRole("heading", { level: 1, name: "Water the plants" })).toBeVisible();
    expect(screen.getByText("Grocy chore 7")).toBeVisible();
    expect(screen.getByText("Assigned to").nextSibling).toHaveTextContent("Anna B.");
    expect(screen.getByText("Next due").nextSibling).toHaveTextContent(/2026/);
    expect(screen.getByRole("link", { name: /Open in Grocy/ })).toHaveAttribute("href", `${GROCY}/chore/7`);
  });

  it("leaves the assignee out when Grocy returns none", async () => {
    await open("/grocycode/c/7", { [C]: { ...CHORE, assigned_to: null } });
    await screen.findByRole("heading", { level: 1, name: "Water the plants" });
    expect(screen.queryByText("Assigned to")).toBeNull();
  });

  it("an unknown chore is said to be unknown", async () => {
    await open("/grocycode/c/7", { [C]: new Response("{}", { status: 404 }) });
    expect(await screen.findByText("Grocy has no chore with the ID 7.")).toBeVisible();
  });
});

describe("the Grocycode page, other paths", () => {
  it("a product kind or a bad id is a not-found page and asks Grocy nothing", async () => {
    const { calls } = await open("/grocycode/p/4", {});
    expect(await screen.findByRole("heading", { name: /not found/i })).toBeVisible();
    expect(calls.filter((c) => c.path.includes("/lookup/grocy/"))).toEqual([]);
  });
});
