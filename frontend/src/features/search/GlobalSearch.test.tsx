// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderApp } from "../../test-utils";
import { job, mockApi, PRINTER_A, PRINTER_B } from "../test-api";

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
    mockApi({ "GET /api/v1/lookup/grocy/42": item("grocy", "42"), "GET /api/v1/printers": [] });
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
    mockApi({ "GET /api/v1/lookup/snipeit/42": item("snipeit", "42"), "GET /api/v1/printers": [] });
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
    mockApi({ "GET /api/v1/lookup/spoolman/5": item("spoolman", "5"), "GET /api/v1/printers": [] });
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

  it("lists printers and jobs after the integration lookups, under their own headings", async () => {
    const wanted = job("0f3a9c1e-7b2d-4e5f-8a6b-1c2d3e4f5a6b", PRINTER_A.id, "queued", { template_key: "asset-label" });
    mockApi({ "GET /api/v1/printers": [PRINTER_A, PRINTER_B], "GET /api/v1/jobs": [wanted] });
    const { router } = await renderApp({ path: "/", info: { integrations: set(true, false, false) } });
    await userEvent.type(field(), "office");
    const list = await screen.findByRole("listbox", { name: "Search results" });
    await within(list).findByRole("option", { name: /Office QL-820NWB/ });
    expect(within(list).getAllByRole("option").map((o) => o.textContent)).toEqual(["Look up office in Snipe-IT", "Office QL-820NWBoffice-ql"]);
    expect(within(list).getByText("Printers")).toBeVisible();
    await userEvent.click(within(list).getByRole("option", { name: /Office QL-820NWB/ }));
    expect(router.state.location.pathname).toBe(`/printers/${PRINTER_B.id}`);

    await userEvent.type(field(), "0f3a9c");
    await within(await screen.findByRole("listbox")).findByRole("option", { name: /0f3a9c1e/ });
    expect(within(screen.getByRole("listbox")).getByText("Jobs")).toBeVisible();
  });

  it("/ focuses the field, unless the person is typing somewhere else", async () => {
    mockApi({ "GET /api/v1/printers": [] });
    await renderApp({ path: "/", info: { integrations: set(true, false, false) } });
    expect(field()).not.toHaveFocus();
    await userEvent.keyboard("/");
    expect(field()).toHaveFocus();
    expect(field()).toHaveValue("");

    field().blur();
    const other = document.createElement("textarea");
    document.body.append(other);
    other.focus();
    await userEvent.keyboard("/");
    expect(other).toHaveFocus();
    expect(other).toHaveValue("/");
    other.remove();
  });
});
