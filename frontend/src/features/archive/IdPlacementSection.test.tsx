// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { I18nProvider } from "@lingui/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { i18n, initI18n } from "../../i18n";
import { mockApi, SHEET_TYPE } from "../test-api";
import type { SheetTypeDetail } from "./api";
import { IdPlacementSection } from "./IdPlacementSection";

const ULTRAGRIP = {
  key: "avery-zweckform-ultragrip",
  name: "Avery Zweckform ultragrip",
  page_size: "A4" as const,
  strips: [
    { x_mm: 33.5, y_mm: 22, w_mm: 22, h_mm: 253 },
    { x_mm: 154.5, y_mm: 22, w_mm: 22, h_mm: 253 },
  ],
  origin: "seed" as const,
  types_in_use: 2,
};
const T3490: SheetTypeDetail = {
  ...SHEET_TYPE,
  key: "avery-zweckform-3490",
  geometry: { page_size: "A4", page_w: 210, page_h: 297, label_w: 70, label_h: 36, cols: 3, rows: 8, pitch_x: 70, pitch_y: 36, margin_top: 4.5, margin_left: 0, corner_radius: null, shape: "rectangle" },
  id_placement: "auto",
  id_placement_resolved: "back_side",
  id_cell: null,
  backing_design: ULTRAGRIP,
  versions: [],
};
const T_MARGIN: SheetTypeDetail = { ...SHEET_TYPE, id_placement: "auto", id_placement_resolved: "margin", versions: [] };

async function show(type: SheetTypeDetail, admin = true, language: "en" | "de" = "en") {
  await initI18n(language);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <I18nProvider i18n={i18n}>
        <IdPlacementSection type={type} admin={admin} />
      </I18nProvider>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("where the sheet code goes", () => {
  it("auto shows the resolved option selected and the automatic note", async () => {
    mockApi({ "GET /api/v1/backing-designs": [ULTRAGRIP] });
    await show(T3490);
    expect(screen.getByRole("radio", { name: /Back side/ })).toBeChecked();
    expect(screen.getByText("Default for this sheet")).toBeVisible();
    expect(screen.getByText("Chosen automatically from the usable margin. You can change it.")).toBeVisible();
  });

  it("margin is disabled with the reason when the type has no usable band", async () => {
    mockApi({ "GET /api/v1/backing-designs": [ULTRAGRIP] });
    await show(T3490);
    expect(screen.getByRole("radio", { name: /Margin/ })).toBeDisabled();
    expect(screen.getByText(/Not available for this sheet: no margin is wide enough/)).toBeVisible();
  });

  it('choosing reserved cell shows the cell select with "1 (top left)"', async () => {
    mockApi({ "GET /api/v1/backing-designs": [ULTRAGRIP] });
    await show(T3490);
    expect(screen.queryByRole("button", { name: /Cell/ })).toBeNull();
    await userEvent.click(screen.getByRole("radio", { name: /Reserved cell/ }));
    expect(screen.getByRole("button", { name: /Cell/ })).toHaveTextContent("1 (top left)");
  });

  it("save sends id_placement and id_cell", async () => {
    const { calls } = mockApi({
      "GET /api/v1/backing-designs": [ULTRAGRIP],
      [`PATCH /api/v1/sheet-types/${T3490.key}`]: { ...T3490, id_placement: "cell", id_cell: 2 },
    });
    await show(T3490);
    await userEvent.click(screen.getByRole("radio", { name: /Reserved cell/ }));
    await userEvent.click(screen.getByRole("button", { name: /Cell/ }));
    await userEvent.click(await screen.findByRole("option", { name: "2" }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
    const body = JSON.parse(calls.find((c) => c.method === "PATCH")!.body!);
    expect(body).toEqual({ id_placement: "cell", id_cell: 2, backing_design: ULTRAGRIP.key });
  });

  it("keeps auto when the automatic option is saved, and offers the margin type its margin", async () => {
    mockApi({ "GET /api/v1/backing-designs": [ULTRAGRIP] });
    await show(T_MARGIN);
    expect(screen.getByRole("radio", { name: /Margin/ })).toBeChecked();
    expect(screen.getByRole("radio", { name: /Margin/ })).toBeEnabled();
  });

  it("a read-only user sees the setting but no Save", async () => {
    mockApi({ "GET /api/v1/backing-designs": [ULTRAGRIP] });
    await show(T3490, false);
    expect(screen.getByRole("radio", { name: /Back side/ })).toBeChecked();
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
  });

  it("de: options are German", async () => {
    mockApi({ "GET /api/v1/backing-designs": [ULTRAGRIP] });
    await show(T3490, true, "de");
    expect(screen.getByRole("heading", { name: "Wo der Bogencode hinkommt" })).toBeVisible();
    expect(screen.getByRole("radio", { name: /Rand/ })).toBeDisabled();
    expect(screen.getByRole("radio", { name: /Rückseite/ })).toBeChecked();
    expect(screen.getByRole("radio", { name: /Reservierte Zelle/ })).toBeVisible();
    expect(screen.getByText("Standard für diesen Bogen")).toBeVisible();
    await initI18n("en");
  });
});
