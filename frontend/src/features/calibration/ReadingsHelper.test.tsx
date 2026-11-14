// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { I18nProvider } from "@lingui/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { i18n, initI18n } from "../../i18n";
import type * as Controls from "../settings/controls";

// Counts renders of the select, which is the expensive part of a reading row (two per row).
const renders = vi.hoisted(() => ({ select: 0 }));
vi.mock("../settings/controls", async (importOriginal) => {
  const original = await importOriginal<typeof Controls>();
  return {
    ...original,
    SelectField: (props: Parameters<typeof original.SelectField>[0]) => {
      renders.select++;
      return original.SelectField(props);
    },
  };
});

import { ReadingsHelper } from "./ReadingsHelper";

beforeAll(() => initI18n("en"));

describe("the readings rows", () => {
  it("editing one row does not render the other rows again", () => {
    render(
      <I18nProvider i18n={i18n}>
        <QueryClientProvider client={new QueryClient()}>
          <ReadingsHelper printerId="p" tray="main" typeKey="T" version={1} cols={4} rows={12} onFitted={() => {}} />
        </QueryClientProvider>
      </I18nProvider>,
    );
    expect(screen.getAllByRole("group", { name: /^Reading \d/ })).toHaveLength(4);

    const before = renders.select;
    fireEvent.change(screen.getAllByRole("textbox", { name: /^Across at/ })[0]!, { target: { value: "0,5" } });
    expect(screen.getAllByRole("textbox", { name: /^Across at/ })[0]).toHaveValue("0,5");

    // Row 1 renders its two selects again; rows 2 to 4 (six selects) do not.
    expect(renders.select - before).toBe(2);
  });
});
