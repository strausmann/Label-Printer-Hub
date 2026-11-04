import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderApp } from "../../test-utils";
import { mockApi } from "../test-api";

afterEach(() => vi.unstubAllGlobals());

const set = (snipeit: boolean, grocy: boolean, spoolman: boolean) => [
  { name: "snipeit" as const, configured: snipeit },
  { name: "grocy" as const, configured: grocy },
  { name: "spoolman" as const, configured: spoolman },
];
const field = () => screen.getByRole("combobox", { name: "Search" });
const item = (app: string, id: string) => ({ app, id, name: "Cordless drill", url: `https://assets.example.invalid/${app}/${id}`, extra: {} });

describe("global search", () => {
  it("offers a lookup in every configured integration under a heading, and nothing for the others", async () => {
    mockApi({});
    await renderApp({ path: "/", info: { integrations: set(true, true, false) } });
    await userEvent.type(field(), "HH-AK0042");
    const list = await screen.findByRole("listbox", { name: "Search results" });
    const options = within(list).getAllByRole("option");
    expect(options.map((o) => o.textContent)).toEqual(["Look up HH-AK0042 in Snipe-IT", "Look up HH-AK0042 in Grocy"]);
    expect(within(list).getByText("Look up in an integration")).toBeVisible();
    expect(within(list).queryByText(/Spoolman/)).toBeNull();
  });

  it("no integration set up, no suggestion and no list", async () => {
    mockApi({});
    await renderApp({ path: "/", info: { integrations: set(false, false, false) } });
    await userEvent.type(field(), "42");
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("the first suggestion is active; arrows move, Enter opens it", async () => {
    mockApi({ "GET /api/lookup/grocy/42": item("grocy", "42"), "GET /api/printers": [] });
    const { router } = await renderApp({ path: "/", info: { integrations: set(true, true, true) } });
    await userEvent.type(field(), "42");
    const options = await screen.findAllByRole("option");
    expect(options[0]).toHaveAttribute("aria-selected", "true");
    expect(field()).toHaveAttribute("aria-activedescendant", options[0]!.id);
    await userEvent.keyboard("{ArrowDown}");
    expect(screen.getAllByRole("option")[1]).toHaveAttribute("aria-selected", "true");
    await userEvent.keyboard("{Enter}");
    expect(router.state.location.pathname).toBe("/lookup/grocy/42");
    expect(field()).toHaveValue("");
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("Enter straight after typing opens the first one (Snipe-IT)", async () => {
    mockApi({ "GET /api/lookup/snipeit/42": item("snipeit", "42"), "GET /api/printers": [] });
    const { router } = await renderApp({ path: "/", info: { integrations: set(true, true, true) } });
    await userEvent.type(field(), "42{Enter}");
    expect(router.state.location.pathname).toBe("/lookup/snipeit/42");
  });

  it("ArrowUp wraps to the last, ArrowDown wraps to the first", async () => {
    mockApi({});
    await renderApp({ path: "/", info: { integrations: set(true, true, true) } });
    await userEvent.type(field(), "x");
    await screen.findAllByRole("option");
    await userEvent.keyboard("{ArrowUp}");
    expect(screen.getAllByRole("option")[2]).toHaveAttribute("aria-selected", "true");
    await userEvent.keyboard("{ArrowDown}");
    expect(screen.getAllByRole("option")[0]).toHaveAttribute("aria-selected", "true");
  });

  it("clicking a suggestion opens it", async () => {
    mockApi({ "GET /api/lookup/spoolman/5": item("spoolman", "5"), "GET /api/printers": [] });
    const { router } = await renderApp({ path: "/", info: { integrations: set(false, false, true) } });
    await userEvent.type(field(), "5");
    await userEvent.click(await screen.findByRole("option", { name: "Look up 5 in Spoolman" }));
    expect(router.state.location.pathname).toBe("/lookup/spoolman/5");
  });

  it("Escape closes the list and keeps the text", async () => {
    mockApi({});
    await renderApp({ path: "/", info: { integrations: set(true, false, false) } });
    await userEvent.type(field(), "42");
    await screen.findByRole("listbox");
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(field()).toHaveValue("42");
    expect(field()).toHaveAttribute("aria-expanded", "false");
  });

  it("a pasted label link offers the one item it names", async () => {
    mockApi({});
    await renderApp({ path: "/", info: { integrations: set(true, true, true) } });
    await userEvent.click(field());
    await userEvent.paste("https://hub.example.invalid/loc/17");
    const options = await screen.findAllByRole("option");
    expect(options.map((o) => o.textContent)).toEqual(["Open loc:17 in Snipe-IT"]);
  });

  it("clearing the field closes the list", async () => {
    mockApi({});
    await renderApp({ path: "/", info: { integrations: set(true, false, false) } });
    await userEvent.type(field(), "4");
    await screen.findByRole("listbox");
    await userEvent.clear(field());
    expect(screen.queryByRole("listbox")).toBeNull();
  });
});
