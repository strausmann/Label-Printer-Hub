// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MAX_COPIES } from "../../lookup/cart";
import { LINE, cartView, itemView, previews, resetBetweenTests } from "./SheetSection.kit";
import { USED_17, body, previewFor, routes } from "./testkit";
import type * as Debounced from "./useDebounced";

vi.mock("./useDebounced", async (importOriginal) => {
  const real = await importOriginal<typeof Debounced>();
  return { useDebounced: <T,>(value: T, ms: number) => real.useDebounced(value, Math.min(ms, 20)) };
});
vi.setConfig({ testTimeout: 15_000 });
resetBetweenTests();

const section = () => screen.getByRole("region", { name: "Print onto a sheet" });
const countField = () => within(section()).getByRole("spinbutton", { name: "Number of labels" });
const FIVE = [2, 3, 4, 5, 6];

describe("the number of labels in the sheet section", () => {
  it("the sheet section shows the number of labels", async () => {
    await itemView(routes(), 3);
    expect(countField()).toHaveValue(3);
    expect(countField()).toHaveAttribute("min", "1");
    expect(countField()).toHaveAttribute("max", String(MAX_COPIES));
  });

  it("changing it updates the preview request count", async () => {
    const { calls } = await itemView(routes({ preview: previewFor("L4736-0001", FIVE, [1]) }), 1);
    fireEvent.change(countField(), { target: { value: "5" } });
    await waitFor(() => expect(body(previews(calls).at(-1)!).items).toHaveLength(5));
    expect(await within(section()).findByText("5 labels → cells 2–6 on L4736-0001")).toBeVisible();
  });

  it("the copies field and the sheet field show the same value", async () => {
    await itemView(routes(), 1);
    fireEvent.change(countField(), { target: { value: "4" } });
    await waitFor(() => expect(screen.getByRole("spinbutton", { name: "Copies" })).toHaveValue(4));
    fireEvent.change(screen.getByRole("spinbutton", { name: "Copies" }), { target: { value: "7" } });
    await waitFor(() => expect(countField()).toHaveValue(7));
  });

  it("clamps to 1 and the copies limit", async () => {
    await itemView(routes(), 1);
    fireEvent.change(countField(), { target: { value: "99" } });
    expect(countField()).toHaveValue(MAX_COPIES);
    fireEvent.change(countField(), { target: { value: "0" } });
    expect(countField()).toHaveValue(1);
  });

  it("a sheet that does not exist yet is named as a new sheet", async () => {
    await itemView(routes({ preview: previewFor(null, [1, 2]) }), 2);
    expect(await within(section()).findByText("2 labels → cells 1–2 on a new sheet")).toBeVisible();
  });

  it("the cart's sheet section has no number field", async () => {
    await cartView("/cart", [LINE("1", 2)], routes({ preview: previewFor("L4736-0001", [2, 3], USED_17) }));
    await screen.findByRole("heading", { level: 2, name: "Print onto a sheet" });
    expect(within(section()).queryByRole("spinbutton", { name: "Number of labels" })).toBeNull();
  });
});
