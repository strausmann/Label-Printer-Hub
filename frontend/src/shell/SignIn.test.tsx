// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { I18nProvider } from "@lingui/react";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import { i18n, initI18n } from "../i18n";
import { createQueryClient } from "../app/queryClient";
import { INFO_KEY } from "../app/session";
import { INFO } from "../test-utils";
import { SignIn } from "./SignIn";

const SOURCE = "https://example.invalid/fork/tree/v1.1.0";

async function renderSignIn(onSignIn: (key: string) => Promise<void>, lang: "en" | "de" = "en") {
  await initI18n(lang);
  const queryClient = createQueryClient();
  queryClient.setQueryData(INFO_KEY, { ...INFO, source_url: SOURCE });
  return render(
    <I18nProvider i18n={i18n}>
      <QueryClientProvider client={queryClient}>
        <SignIn onSignIn={onSignIn} />
      </QueryClientProvider>
    </I18nProvider>,
  );
}

describe("SignIn", () => {
  it("names the app with the Labelyard wordmark", async () => {
    await renderSignIn(async () => undefined);
    const heading = screen.getByRole("heading", { level: 1 });
    expect(heading).toHaveAccessibleName("Labelyard");
    expect(within(heading).getByRole("img", { name: "Labelyard" })).toBeInTheDocument();
  });

  it.each([
    ["en", "The self-hosted Label Printer Hub for all your labels"],
    ["de", "Der selbst gehostete Label Printer Hub für all deine Etiketten"],
  ] as const)("shows the tagline in %s", async (lang, tagline) => {
    await renderSignIn(async () => undefined, lang);
    expect(screen.getByText(tagline)).toBeInTheDocument();
  });

  it("has one password field that is never remembered", async () => {
    await renderSignIn(async () => undefined);
    const field = screen.getByLabelText("API key");
    expect(field).toHaveAttribute("type", "password");
    expect(field).toHaveAttribute("autocomplete", "off");
  });

  it("submits key and clears the field", async () => {
    const onSignIn = vi.fn(async () => undefined);
    await renderSignIn(onSignIn);
    const field = screen.getByLabelText("API key");
    await userEvent.type(field, "not-a-real-key");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(onSignIn).toHaveBeenCalledWith("not-a-real-key"));
    expect(field).toHaveValue("");
  });

  it("source link before sign-in", async () => {
    await renderSignIn(async () => undefined);
    const link = screen.getByRole("link", { name: "Source code" });
    expect(link).toHaveAttribute("href", SOURCE);
    expect(link.getAttribute("rel")).toContain("noopener");
  });

  it("gives the source link a tap target of at least 44 px", async () => {
    await renderSignIn(vi.fn(async () => undefined));
    expect(screen.getByRole("link", { name: "Source code" }).className).toMatch(/\bmin-h-11\b/);
  });

  it("does not submit an empty field", async () => {
    const onSignIn = vi.fn(async () => undefined);
    await renderSignIn(onSignIn);
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(onSignIn).not.toHaveBeenCalled();
  });

  it.each([
    [401, "invalid_api_key", "That key was not accepted."],
    [403, "scope_too_low", "This key can only read. Sign in with a key that has print or admin scope."],
    [429, "rate_limit_exceeded", "Too many attempts. Wait a minute and try again."],
    [0, "network_error", "The server cannot be reached."],
    [500, null, "Something went wrong."],
  ])("explains a %i failure", async (status, code, message) => {
    await renderSignIn(async () => {
      throw new ApiError(status, code, "detail");
    });
    await userEvent.type(screen.getByLabelText("API key"), "x");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(screen.getByLabelText("API key")).toHaveValue("");
  });
});
