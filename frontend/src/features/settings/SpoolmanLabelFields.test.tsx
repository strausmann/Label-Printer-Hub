// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderApp, widenAppWaits } from "../../test-utils";
import { KEY_ADMIN, mockApi, settingsList } from "../test-api";

afterEach(() => vi.unstubAllGlobals());

const CONFIGURED = [
  { name: "snipeit" as const, configured: false },
  { name: "grocy" as const, configured: false },
  { name: "spoolman" as const, configured: true },
];

async function openSpoolman(extra: Record<string, unknown> = {}, language: "en" | "de" = "en") {
  const api = mockApi({
    "GET /api/v1/settings": settingsList({ "integrations.spoolman.url": { value: "https://spoolman.example.invalid", is_set: true } }),
    "GET /api/v1/admin/api-keys": [KEY_ADMIN],
    "PUT /api/v1/settings": () => settingsList({ "integrations.spoolman.url": { value: "https://spoolman.example.invalid", is_set: true } }),
    "POST /api/v1/settings/integrations/spoolman/test": { ok: true, status: 200, detail: "ok" },
    ...extra,
  });
  await renderApp({ path: "/settings/integrations", info: { integrations: CONFIGURED }, language });
  const card = await screen.findByRole("group", { name: "Spoolman" });
  return { ...api, card };
}

const open = async (card: HTMLElement, name = "Label fields") => userEvent.click(within(card).getByRole("button", { name }));

// Each test boots the whole app (the first one also loads its modules); on a loaded runner the first one passed the
// default 5 s limit. The per-test limit and the findBy window are widened for this file only, like the other
// whole-app test files.
vi.setConfig({ testTimeout: 15_000 });
widenAppWaits();

describe("the Spoolman label fields (#346)", () => {
  it("the label fields are collapsed and open on press", async () => {
    const { card } = await openSpoolman();
    const trigger = within(card).getByRole("button", { name: "Label fields" });
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(within(card).queryByRole("textbox", { name: "Pressure advance field" })).toBeNull();
    await userEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(within(card).getByRole("textbox", { name: "Pressure advance field" })).toBeVisible();
  });

  it("the five key fields and the title source show the defaults", async () => {
    const { card } = await openSpoolman();
    await open(card);
    const value = (name: string) => within(card).getByRole("textbox", { name });
    expect(value("Nozzle temperature field")).toHaveValue("nozzle_temperature");
    expect(value("Pressure advance field")).toHaveValue("flowdynamics");
    expect(value("Flow ratio field")).toHaveValue("flowrate");
    expect(value("Drying temperature field")).toHaveValue("drying_condiftions_temp");
    expect(value("Drying time field")).toHaveValue("drying_condiftions_time");
    expect(within(card).getByRole("button", { name: /Bar shows$/ })).toHaveTextContent("Material");
    expect(within(card).getByText("Keys of the extra fields in your Spoolman.")).toBeVisible();
  });

  it("the German labels", async () => {
    const { card } = await openSpoolman({}, "de");
    await open(card, "Etikettenfelder");
    expect(within(card).getByRole("textbox", { name: "Feld Pressure Advance" })).toBeVisible();
    await userEvent.click(within(card).getByRole("button", { name: /Balken zeigt$/ }));
    expect(await screen.findByRole("option", { name: "Filamentname" })).toBeInTheDocument();
  });

  it("an edited key is saved with the section", async () => {
    const { card, calls } = await openSpoolman();
    await open(card);
    const field = within(card).getByRole("textbox", { name: "Pressure advance field" });
    await userEvent.clear(field);
    await userEvent.type(field, "pa");
    await userEvent.click(within(card).getByRole("button", { name: "Save" }));
    const put = calls.find((c) => c.method === "PUT" && c.path === "/api/v1/settings")!;
    expect(JSON.parse(put.body!)).toEqual({ values: { "integrations.spoolman.label.pressure_advance_field": "pa" } });
  });

  it("an empty key is allowed", async () => {
    const { card, calls } = await openSpoolman();
    await open(card);
    await userEvent.clear(within(card).getByRole("textbox", { name: "Drying time field" }));
    const save = within(card).getByRole("button", { name: "Save" });
    expect(save).toBeEnabled();
    await userEvent.click(save);
    const put = calls.find((c) => c.method === "PUT" && c.path === "/api/v1/settings")!;
    expect(JSON.parse(put.body!)).toEqual({ values: { "integrations.spoolman.label.drying_time_field": "" } });
  });

  it("the title source switches to the filament name", async () => {
    const { card, calls } = await openSpoolman();
    await open(card);
    await userEvent.click(within(card).getByRole("button", { name: /Bar shows$/ }));
    await userEvent.click(await screen.findByRole("option", { name: "Filament name" }));
    await userEvent.click(within(card).getByRole("button", { name: "Save" }));
    const put = calls.find((c) => c.method === "PUT" && c.path === "/api/v1/settings")!;
    expect(JSON.parse(put.body!)).toEqual({ values: { "integrations.spoolman.label.title_source": "name" } });
  });

  it("editing a label field does not invalidate the connection test", async () => {
    const { card } = await openSpoolman();
    await userEvent.click(within(card).getByRole("button", { name: "Test connection" }));
    expect(await within(card).findByText("Works")).toBeVisible();
    await open(card);
    await userEvent.type(within(card).getByRole("textbox", { name: "Flow ratio field" }), "x");
    expect(within(card).getByText("Works")).toBeVisible();
  });
});
