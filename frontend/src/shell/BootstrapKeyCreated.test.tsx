// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { I18nProvider } from "@lingui/react";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import { i18n, initI18n } from "../i18n";
import { createQueryClient } from "../app/queryClient";
import { INFO_KEY } from "../app/session";
import { INFO } from "../test-utils";
import { BootstrapKeyCreated } from "./BootstrapKeyCreated";

const SOURCE = "https://example.invalid/fork/tree/v1.1.0";

async function renderFlow(props: Partial<React.ComponentProps<typeof BootstrapKeyCreated>> = {}) {
  await initI18n("en");
  const onCreate = props.onCreate ?? vi.fn(async () => "lh_pat_fake-key-for-tests");
  const onContinue = props.onContinue ?? vi.fn(async () => undefined);
  const queryClient = createQueryClient();
  queryClient.setQueryData(INFO_KEY, { ...INFO, source_url: SOURCE });
  render(
    <I18nProvider i18n={i18n}>
      <QueryClientProvider client={queryClient}>
        <BootstrapKeyCreated onCreate={onCreate} onContinue={onContinue} />
      </QueryClientProvider>
    </I18nProvider>,
  );
  return { onCreate, onContinue };
}

describe("BootstrapKeyCreated", () => {
  it("offers to create the first admin key and nothing else", async () => {
    await renderFlow();
    expect(screen.getByRole("heading", { level: 1, name: "Create the first admin key" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create admin key" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Continue" })).toBeNull();
  });

  it("source link", async () => {
    await renderFlow();
    const link = screen.getByRole("link", { name: "Source code" });
    expect(link).toHaveAttribute("href", SOURCE);
    expect(link.getAttribute("rel")).toContain("noopener");
  });

  it("shows the key once, with the removal hint, then continues with it", async () => {
    const { onCreate, onContinue } = await renderFlow();
    await userEvent.click(screen.getByRole("button", { name: "Create admin key" }));
    await waitFor(() => expect(onCreate).toHaveBeenCalledTimes(1));
    expect(await screen.findByLabelText("Your new admin key")).toHaveValue("lh_pat_fake-key-for-tests");
    expect(screen.getByText(/shown only once/)).toBeInTheDocument();
    expect(screen.getByText("LABELYARD_BOOTSTRAP_ADMIN_KEY")).toBeInTheDocument();
    expect(screen.getByText(/Remove/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create admin key" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(onContinue).toHaveBeenCalledWith("lh_pat_fake-key-for-tests");
  });

  it("copies the key", async () => {
    const writeText = vi.fn(async () => undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    await renderFlow();
    await userEvent.click(screen.getByRole("button", { name: "Create admin key" }));
    await userEvent.click(await screen.findByRole("button", { name: "Copy key" }));
    expect(writeText).toHaveBeenCalledWith("lh_pat_fake-key-for-tests");
    expect(await screen.findByText("Copied")).toBeInTheDocument();
  });

  it("says so when the clipboard is not available", async () => {
    Object.defineProperty(navigator, "clipboard", { value: undefined, configurable: true });
    await renderFlow();
    await userEvent.click(screen.getByRole("button", { name: "Create admin key" }));
    await userEvent.click(await screen.findByRole("button", { name: "Copy key" }));
    expect(await screen.findByText("Copy failed. Select the key and copy it by hand.")).toBeInTheDocument();
  });

  it("reports a failed creation and allows another try", async () => {
    const onCreate = vi.fn(async () => {
      throw new ApiError(403, "bootstrap_disabled", "disabled");
    });
    await renderFlow({ onCreate });
    await userEvent.click(screen.getByRole("button", { name: "Create admin key" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The key could not be created.");
    expect(screen.getByRole("button", { name: "Create admin key" })).toBeEnabled();
  });
});
