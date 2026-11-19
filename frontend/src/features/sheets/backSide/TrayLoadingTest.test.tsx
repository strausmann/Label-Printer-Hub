// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { I18nProvider } from "@lingui/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { i18n, initI18n } from "../../../i18n";
import { apiErrorBody, mockApi, respond } from "../../test-api";
import { TrayLoadingTest } from "./TrayLoadingTest";

const P = "dddddddd-0000-4000-8000-000000000001";
const BASE = `/api/v1/printers/${P}/trays/manual/loading`;

function show(onSaved = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <I18nProvider i18n={i18n}>
        <TrayLoadingTest printerId={P} trayKey="manual" trayLabel="Tray 1 (manual feed)" onSaved={onSaved} />
      </I18nProvider>
    </QueryClientProvider>,
  );
  return onSaved;
}

beforeEach(() => initI18n("en"));
afterEach(() => vi.unstubAllGlobals());

async function printAndAnswer(crossed: "Yes" | "No", top: "Yes" | "No") {
  await userEvent.click(screen.getByRole("button", { name: "Print test page" }));
  const first = await screen.findByRole("radiogroup", { name: "Is the print on the side with the cross?" });
  await userEvent.click(within(first).getByRole("radio", { name: crossed }));
  const second = screen.getByRole("radiogroup", { name: "Is “TOP” next to the cross?" });
  await userEvent.click(within(second).getByRole("radio", { name: top }));
}


describe("the guided tray loading test", () => {
  it("prints the test page, then asks both questions", async () => {
    const { calls } = mockApi({ [`POST ${BASE}/test-page`]: { job_id: "j1" } });
    show();
    expect(screen.queryByRole("radiogroup")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Print test page" }));
    expect(await screen.findByRole("radiogroup", { name: "Is the print on the side with the cross?" })).toBeVisible();
    expect(screen.getByRole("radiogroup", { name: "Is “TOP” next to the cross?" })).toBeVisible();
    expect(calls.filter((c) => c.method === "POST" && c.path === `${BASE}/test-page`)).toHaveLength(1);
  });

  it("the answers are saved for the tray", async () => {
    const { calls } = mockApi({
      [`POST ${BASE}/test-page`]: { job_id: "j1" },
      [`PUT ${BASE}`]: { print_side: "down", leading_edge: "top" },
    });
    const onSaved = show();
    await printAndAnswer("No", "Yes");
    expect(screen.getByRole("button", { name: "Save for this tray" })).toBeEnabled();
    await userEvent.click(screen.getByRole("button", { name: "Save for this tray" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    const put = calls.find((c) => c.method === "PUT")!;
    expect(JSON.parse(put.body!)).toEqual({ print_side: "down", leading_edge: "top" });
  });

  it("a 409 already-set reloads the stored loading instead of failing", async () => {
    mockApi({
      [`POST ${BASE}/test-page`]: { job_id: "j1" },
      [`PUT ${BASE}`]: () => respond(409, apiErrorBody("tray_loading_already_set", "already set")),
    });
    const onSaved = show();
    await printAndAnswer("Yes", "Yes");
    await userEvent.click(screen.getByRole("button", { name: "Save for this tray" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(screen.getByText("Someone already set this tray; the stored answer is used.")).toBeVisible();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
