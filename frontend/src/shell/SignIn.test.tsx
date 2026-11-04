import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { I18nProvider } from "@lingui/react";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import { i18n, initI18n } from "../i18n";
import { SignIn } from "./SignIn";

async function renderSignIn(onSignIn: (key: string) => Promise<void>) {
  await initI18n("en");
  return render(
    <I18nProvider i18n={i18n}>
      <SignIn onSignIn={onSignIn} />
    </I18nProvider>,
  );
}

describe("SignIn", () => {
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
