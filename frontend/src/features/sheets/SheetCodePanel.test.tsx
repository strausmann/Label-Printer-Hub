// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderApp, SIGNED_IN } from "../../test-utils";
import { apiErrorBody, mockApi, PAGE_CAPABILITIES, PAGE_PRINTER, respond, SHEET_TYPE, sheetRead, type Call } from "../test-api";
import type { SheetRead } from "./api";

const PRINT_SESSION = { ...SIGNED_IN, scope: "print" as const };
const READ_SESSION = { ...SIGNED_IN, scope: "read" as const };
const CODE = "L4736-0001";
const PATH = `/api/v1/sheets/${CODE}`;

vi.setConfig({ testTimeout: 15_000 });
afterEach(() => vi.unstubAllGlobals());

const PRINTING = {
  "GET /api/v1/printers": [PAGE_PRINTER],
  [`GET /api/v1/printers/${PAGE_PRINTER.id}/capabilities`]: PAGE_CAPABILITIES,
  [`GET /api/v1/sheet-types/${SHEET_TYPE.key}`]: { ...SHEET_TYPE, versions: [] },
};

async function open(sheet: SheetRead, extra: Record<string, unknown> = {}, session: typeof PRINT_SESSION | typeof READ_SESSION = PRINT_SESSION) {
  const api = mockApi({ [`GET ${PATH}`]: sheet, ...PRINTING, ...extra });
  await renderApp({ path: `/sheets/${CODE}`, session });
  await screen.findByRole("heading", { level: 1, name: sheet.code });
  return api;
}

const panel = () => screen.getByRole("region", { name: "Sheet code" });
const posts = (calls: Call[], path: string) => calls.filter((c) => c.method === "POST" && c.path === path);
const margin = (over: Partial<SheetRead> = {}) => sheetRead(CODE, { used: [1] }, { id_placement: "margin", id_printed: true, ...over });

describe("the sheet code panel", () => {
  it("a printed margin sheet without a back side: placement, state, no back-side line, both prints", async () => {
    await open(margin());
    expect(within(panel()).getByText(CODE)).toBeVisible();
    expect(within(panel()).getByTestId("sheet-code-state")).toHaveTextContent("In the margin · printed");
    expect(within(panel()).queryByTestId("sheet-code-back")).toBeNull();
    expect(within(panel()).getByRole("button", { name: "Reprint margin code" })).toBeVisible();
    expect(within(panel()).getByRole("button", { name: "Print back side" })).toBeVisible();
    expect(within(panel()).queryByRole("button", { name: "Yes, the back side is printed" })).toBeNull();
  });

  it("a pending extra back side says missing and offers the confirmation", async () => {
    const pending = margin({ back_side_state: "pending", back_side_missing: true });
    const { calls } = await open(pending, {
      [`POST ${PATH}/back-side/confirm`]: { ...pending, back_side_state: "confirmed", back_side_missing: false },
    });
    expect(within(panel()).getByTestId("sheet-code-back")).toHaveTextContent(/Back side:\s*missing/);
    await userEvent.click(within(panel()).getByRole("button", { name: "Yes, the back side is printed" }));
    await waitFor(() => expect(posts(calls, `${PATH}/back-side/confirm`)).toHaveLength(1));
    expect(await within(panel()).findByText("confirmed")).toBeVisible();
    expect(within(panel()).queryByRole("button", { name: "Yes, the back side is printed" })).toBeNull();
  });

  it("a confirmed extra back side says confirmed", async () => {
    await open(margin({ back_side_state: "confirmed" }));
    expect(within(panel()).getByTestId("sheet-code-back")).toHaveTextContent(/Back side:\s*confirmed/);
    expect(within(panel()).queryByRole("button", { name: "Yes, the back side is printed" })).toBeNull();
  });

  it("an unconfirmed back_side sheet: not confirmed, missing, print and confirm, no margin reprint", async () => {
    await open(sheetRead(CODE, { used: [] }, { id_placement: "back_side", id_printed: false, back_side_missing: true }));
    expect(within(panel()).getByTestId("sheet-code-state")).toHaveTextContent("On the back of the liner · not confirmed");
    expect(within(panel()).getByTestId("sheet-code-back")).toHaveTextContent(/missing/);
    expect(within(panel()).getByRole("button", { name: "Print back side" })).toBeVisible();
    expect(within(panel()).getByRole("button", { name: "Yes, the back side is printed" })).toBeVisible();
    expect(within(panel()).queryByRole("button", { name: "Reprint margin code" })).toBeNull();
  });

  it("a manual sheet of a margin type offers Print back side and no margin reprint (fix round 1, I1)", async () => {
    const manual = sheetRead(CODE, { used: [] }, { id_placement: "manual", id_printed: false });
    await open(manual, {
      [`GET /api/v1/sheet-types/${SHEET_TYPE.key}`]: { ...SHEET_TYPE, id_placement: "auto", id_placement_resolved: "margin", versions: [] },
    });
    expect(within(panel()).getByTestId("sheet-code-state")).toHaveTextContent(/^Added by hand$/);
    expect(within(panel()).getByRole("button", { name: "Print back side" })).toBeVisible();
    expect(within(panel()).queryByRole("button", { name: "Reprint margin code" })).toBeNull();
    await userEvent.click(within(panel()).getByRole("button", { name: "Print back side" }));
    expect(await screen.findByRole("dialog", { name: "Print back side" })).toBeVisible();
  });

  it("a pending extra back side on a manual sheet says missing", async () => {
    await open(sheetRead(CODE, { used: [] }, { id_placement: "manual", id_printed: false, back_side_state: "pending", back_side_missing: true }));
    expect(within(panel()).getByTestId("sheet-code-back")).toHaveTextContent(/Back side:\s*missing/);
    expect(within(panel()).getByRole("button", { name: "Yes, the back side is printed" })).toBeVisible();
  });

  it("an unprinted cell sheet offers no back side (its ID cell is still due)", async () => {
    await open(sheetRead(CODE, { used: [] }, { id_placement: "cell", id_printed: false }));
    expect(within(panel()).getByTestId("sheet-code-state")).toHaveTextContent("In a cell · not printed yet");
    expect(within(panel()).queryByRole("button")).toBeNull();
  });

  it("a discarded sheet shows the panel without buttons", async () => {
    await open(margin({ state: "discarded", discarded_at: "2026-11-02T12:00:00Z", back_side_state: "pending" }));
    expect(within(panel()).getByTestId("sheet-code-state")).toHaveTextContent("In the margin · printed");
    expect(within(panel()).queryByRole("button")).toBeNull();
  });

  it("a read key sees the panel without buttons", async () => {
    await open(margin({ back_side_state: "pending", back_side_missing: true }), {}, READ_SESSION);
    expect(within(panel()).getByTestId("sheet-code-back")).toHaveTextContent(/missing/);
    expect(within(panel()).queryByRole("button")).toBeNull();
  });

  it("Reprint margin code sends the printer and tray and closes", async () => {
    const { calls } = await open(margin(), { [`POST ${PATH}/margin-id`]: { job_id: "11111111-1111-4111-8111-111111111111" } });
    await userEvent.click(within(panel()).getByRole("button", { name: "Reprint margin code" }));
    const dialog = await screen.findByRole("dialog", { name: "Reprint margin code" });
    const send = within(dialog).getByRole("button", { name: "Print margin code" });
    await waitFor(() => expect(send).toBeEnabled());
    await userEvent.click(send);
    await waitFor(() => expect(posts(calls, `${PATH}/margin-id`)).toHaveLength(1));
    const sent = JSON.parse(posts(calls, `${PATH}/margin-id`)[0]!.body ?? "null");
    expect(sent.printer).toBe(PAGE_PRINTER.id);
    expect(sent).toHaveProperty("tray");
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Reprint margin code" })).toBeNull());
  });

  it("a refused margin reprint stays open with the reason", async () => {
    await open(margin(), {
      [`POST ${PATH}/margin-id`]: () => respond(422, apiErrorBody("margin_id_does_not_fit", "The sheet code does not fit.")),
    });
    await userEvent.click(within(panel()).getByRole("button", { name: "Reprint margin code" }));
    const dialog = await screen.findByRole("dialog", { name: "Reprint margin code" });
    const send = within(dialog).getByRole("button", { name: "Print margin code" });
    await waitFor(() => expect(send).toBeEnabled());
    await userEvent.click(send);
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("The sheet code does not fit the margin of this sheet on this printer.");
  });
});
