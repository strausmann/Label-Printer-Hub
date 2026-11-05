import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderApp, SIGNED_IN } from "../../test-utils";
import { CART_KEY, reloadCart } from "../lookup/cart";
import { recordRecent, reloadRecent } from "../lookup/recent";
import { mockApi } from "../test-api";

beforeEach(() => {
  localStorage.clear();
  reloadCart();
  reloadRecent();
});
afterEach(() => vi.unstubAllGlobals());

const item = (app: string, id: string) => ({ app, id, name: "Cordless drill", url: `https://assets.example.invalid/${app}/${id}`, extra: {} });
const READ = { ...SIGNED_IN, scope: "read" as const };
/** The page itself: the sidebar and top bar carry their own "Scan" and "Not set up". */
const page = () => within(screen.getByRole("main"));
const NOT_SET_UP = [
  { name: "snipeit" as const, configured: false },
  { name: "grocy" as const, configured: true },
  { name: "spoolman" as const, configured: true },
];

describe("integration start page", () => {
  it("shows the app, its state and a lookup field with the mono font", async () => {
    mockApi({});
    await renderApp({ path: "/integrations/snipeit" });
    expect(screen.getByRole("heading", { level: 1, name: "Snipe-IT" })).toBeVisible();
    expect(screen.getByText("Configured")).toBeVisible();
    expect(screen.queryByText("Connected")).toBeNull();
    const field = screen.getByRole("textbox", { name: "Find an asset or location" });
    expect(field).toHaveFocus();
    expect(field).toHaveClass("font-mono");
    expect(screen.getByRole("button", { name: "Open" })).toBeVisible();
    expect(page().getByRole("link", { name: "Scan" })).toHaveAttribute("href", "/scan");
  });

  it.each([
    ["snipeit", /asset tag.*numeric ID.*label link.*loc:/i, "Find an asset or location", "Scan"],
    ["grocy", /product ID or barcode/i, "Find a product", "Scan barcode"],
    ["spoolman", /spool ID/i, "Find a spool", "Scan"],
  ])("%s has its own hint, label and scan button", async (app, hint, label, scan) => {
    mockApi({});
    await renderApp({ path: `/integrations/${app}` });
    const field = screen.getByRole("textbox", { name: label });
    expect(field).toHaveAccessibleDescription(hint);
    expect(page().getByRole("link", { name: scan })).toBeVisible();
  });

  it("Enter opens the item view with the value as id", async () => {
    mockApi({ "GET /api/lookup/snipeit/42": item("snipeit", "42"), "GET /api/printers": [] });
    const { router } = await renderApp({ path: "/integrations/snipeit" });
    await userEvent.type(screen.getByRole("textbox", { name: "Find an asset or location" }), "42{Enter}");
    expect(router.state.location.pathname).toBe("/lookup/snipeit/42");
    expect(await screen.findByRole("heading", { level: 1, name: "Cordless drill" })).toBeVisible();
  });

  it("the Open button does the same, a loc: value stays a location id", async () => {
    mockApi({ "GET /api/lookup/snipeit/loc%3A17": item("snipeit", "loc:17"), "GET /api/printers": [] });
    const { router } = await renderApp({ path: "/integrations/snipeit" });
    await userEvent.type(screen.getByRole("textbox", { name: "Find an asset or location" }), "loc:17");
    await userEvent.click(screen.getByRole("button", { name: "Open" }));
    // The colon is percent-encoded in the address, the route reads it back as loc:17.
    expect(router.state.location.pathname).toBe("/lookup/snipeit/loc%3A17");
  });

  it("a blank field goes nowhere", async () => {
    mockApi({});
    const { router } = await renderApp({ path: "/integrations/grocy" });
    await userEvent.type(screen.getByRole("textbox", { name: "Find a product" }), "   {Enter}");
    expect(router.state.location.pathname).toBe("/integrations/grocy");
  });

  it.each([
    ["https://hub.example.invalid/asset/42", "/lookup/snipeit/42"],
    ["https://hub.example.invalid/loc/17", "/lookup/snipeit/loc%3A17"],
    ["https://hub.example.invalid/spool/5", "/lookup/spoolman/5"],
    ["https://hub.example.invalid/product/9", "/lookup/grocy/9"],
  ])("a pasted label link %s is routed to %s", async (url, target) => {
    mockApi({ "GET /api/printers": [] });
    const { router } = await renderApp({ path: "/integrations/snipeit" });
    await userEvent.click(screen.getByRole("textbox", { name: "Find an asset or location" }));
    await userEvent.paste(url);
    await userEvent.keyboard("{Enter}");
    expect(router.state.location.pathname).toBe(target);
  });

  it("an unknown app is not found", async () => {
    mockApi({});
    await renderApp({ path: "/integrations/nope" });
    expect(await screen.findByText(/not found/i)).toBeVisible();
  });
});

describe("integration start page: not set up", () => {
  it("says so and sends an admin to the settings", async () => {
    mockApi({});
    await renderApp({ path: "/integrations/snipeit", info: { integrations: NOT_SET_UP } });
    expect(page().getByText("Not set up")).toBeVisible();
    expect(screen.queryByRole("textbox", { name: /Find/ })).toBeNull();
    expect(page().getByRole("link", { name: "Open Settings › Integrations" })).toHaveAttribute("href", "/settings/integrations");
  });

  it("tells a non-admin to ask an admin, without a settings link", async () => {
    mockApi({});
    await renderApp({ path: "/integrations/snipeit", info: { integrations: NOT_SET_UP }, session: READ });
    expect(page().getByText(/ask an admin/i)).toBeVisible();
    expect(page().queryByRole("link", { name: /Settings/ })).toBeNull();
  });
});

describe("recently opened", () => {
  it("lists the last items of this app with id, name, kind and age; other apps do not show", async () => {
    recordRecent("snipeit", { id: "HH-AK0042", name: "Tool chest" }, Date.now() - 2 * 60_000);
    recordRecent("snipeit", { id: "loc:17", name: "Cellar shelf 3" }, Date.now() - 26 * 3600_000);
    recordRecent("grocy", { id: "118", name: "Oats" });
    mockApi({});
    await renderApp({ path: "/integrations/snipeit" });
    const list = screen.getByRole("list", { name: "Recently opened" });
    const rows = within(list).getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(within(rows[0]!).getByText("loc:17").tagName).toBe("CODE");
    expect(within(rows[0]!).getByRole("link", { name: /Cellar shelf 3/ })).toHaveAttribute("href", "/lookup/snipeit/loc%3A17");
    expect(within(rows[0]!).getByText(/Location · yesterday/)).toBeVisible();
    expect(within(rows[1]!).getByText(/Asset · 2 minutes ago/)).toBeVisible();
    expect(screen.queryByText("Oats")).toBeNull();
    expect(screen.getByText(/only in this browser/i)).toBeVisible();
  });

  it("says so when nothing was opened yet", async () => {
    mockApi({});
    await renderApp({ path: "/integrations/spoolman" });
    expect(screen.getByText("Nothing opened yet.")).toBeVisible();
  });

  it("the Print chip puts the item in the cart with the default layout", async () => {
    recordRecent("snipeit", { id: "HH-AK0042", name: "Tool chest" });
    mockApi({});
    await renderApp({ path: "/integrations/snipeit" });
    await userEvent.click(screen.getByRole("button", { name: "Print Tool chest" }));
    expect(JSON.parse(localStorage.getItem(CART_KEY) ?? "[]")).toEqual([
      { app: "snipeit", id: "HH-AK0042", name: "Tool chest", content_type: "qr_two_lines", copies: 1 },
    ]);
    expect(await screen.findByText("Added to the cart: Tool chest")).toBeVisible();
    expect(screen.getByRole("link", { name: "Cart (1)" })).toBeVisible();
  });

  it("opening an item records it, a failed lookup does not", async () => {
    mockApi({ "GET /api/lookup/grocy/118": item("grocy", "118"), "GET /api/printers": [] });
    await renderApp({ path: "/lookup/grocy/118" });
    await screen.findByRole("heading", { level: 1, name: "Cordless drill" });
    expect(JSON.parse(localStorage.getItem("lph.recent.grocy") ?? "[]")).toMatchObject([{ id: "118", name: "Cordless drill", kind: "product" }]);
  });
});

describe("link to the app itself", () => {
  const sidebar = () => within(screen.getByRole("navigation", { name: "Main" }));

  it("appears once an item of the app was shown in this session, never before", async () => {
    mockApi({
      "GET /api/lookup/snipeit/42": { ...item("snipeit", "42"), url: "https://assets.example.invalid/hardware/42" },
      "GET /api/printers": [],
    });
    await renderApp({ path: "/integrations/snipeit" });
    expect(page().queryByRole("link", { name: /Open Snipe-IT/ })).toBeNull();

    await userEvent.type(screen.getByRole("textbox", { name: "Find an asset or location" }), "42{Enter}");
    await screen.findByRole("heading", { level: 1, name: "Cordless drill" });
    await userEvent.click(sidebar().getByRole("link", { name: "Snipe-IT" }));
    const link = await page().findByRole("link", { name: /Open Snipe-IT/ });
    expect(link).toHaveAttribute("href", "https://assets.example.invalid");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("is left out when the deep link is not a web link in a known shape", async () => {
    mockApi({
      "GET /api/lookup/snipeit/42": { ...item("snipeit", "42"), url: "javascript:alert(1)" },
      "GET /api/printers": [],
    });
    await renderApp({ path: "/lookup/snipeit/42" });
    await screen.findByRole("heading", { level: 1, name: "Cordless drill" });
    await userEvent.click(sidebar().getByRole("link", { name: "Snipe-IT" }));
    await page().findByRole("heading", { level: 1, name: "Snipe-IT" });
    expect(page().queryByRole("link", { name: /Open Snipe-IT/ })).toBeNull();
  });
});

describe("sign out", () => {
  it("forgets the recently opened lists of this browser", async () => {
    recordRecent("snipeit", { id: "HH-AK0042", name: "Tool chest" });
    recordRecent("grocy", { id: "118", name: "Oats" });
    mockApi({ "DELETE /api/v1/auth/session": null });
    await renderApp({ path: "/integrations/snipeit" });
    expect(page().getByText("Tool chest")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Sign out" }));
    await vi.waitFor(() => expect(localStorage.getItem("lph.recent.snipeit")).toBeNull());
    expect(localStorage.getItem("lph.recent.grocy")).toBeNull();
  });
});
