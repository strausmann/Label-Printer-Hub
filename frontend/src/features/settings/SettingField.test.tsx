import { I18nProvider } from "@lingui/react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { i18n, initI18n } from "../../i18n";
import { settingView } from "../test-api";
import { SettingField } from "./SettingField";

async function renderField(props: Partial<React.ComponentProps<typeof SettingField>> & Pick<React.ComponentProps<typeof SettingField>, "view">) {
  await initI18n("en");
  const onChange = vi.fn();
  render(
    <I18nProvider i18n={i18n}>
      <SettingField label="Field" value="" onChange={onChange} {...props} />
    </I18nProvider>,
  );
  return { onChange };
}

describe("SettingField", () => {
  it("locked field is read-only and says Set by the container", async () => {
    const { onChange } = await renderField({
      label: "Public URL",
      value: "https://hub.example.invalid",
      view: settingView("general.public_url", "url", { value: "https://hub.example.invalid", is_set: true, locked: true }),
    });
    const input = screen.getByRole("textbox", { name: "Public URL" });
    expect(input).toHaveValue("https://hub.example.invalid");
    expect(input).toHaveAttribute("readonly");
    expect(screen.getByText("Set by the container")).toBeVisible();
    await userEvent.type(input, "x");
    expect(onChange).not.toHaveBeenCalled();
  });

  it("locked secret says it is set without any input", async () => {
    await renderField({ label: "Token", view: settingView("integrations.grocy.api_key", "secret", { is_set: true, locked: true }) });
    expect(screen.queryByLabelText("Token")).toBeNull();
    expect(screen.getByText("Set by the container")).toBeVisible();
  });

  it("secret input never shows a value", async () => {
    // Even a misbehaving server that sent a value must not reach the field.
    await renderField({
      label: "API key",
      view: settingView("integrations.snipeit.api_key", "secret", { is_set: true, value: "leaked-fake-value" }),
    });
    const input = screen.getByLabelText("API key");
    expect(input).toHaveValue("");
    expect(input).toHaveAttribute("type", "password");
    expect(input).toHaveAttribute("placeholder", "Saved — enter a new value to replace");
    expect(document.body.textContent).not.toContain("leaked-fake-value");
  });

  it("secret that is not set says Not set", async () => {
    await renderField({ label: "API key", view: settingView("integrations.grocy.api_key", "secret") });
    expect(screen.getByLabelText("API key")).toHaveAttribute("placeholder", "Not set");
  });

  it("undecryptable shows warning", async () => {
    await renderField({
      label: "API key",
      view: settingView("integrations.snipeit.api_key", "secret", { is_set: true, state: "undecryptable" }),
    });
    expect(screen.getByText("Can't be read with the current secret key — enter it again")).toBeVisible();
  });

  it("an environment secret without an environment URL explains what to do", async () => {
    await renderField({
      label: "API key",
      view: settingView("integrations.snipeit.api_key", "secret", { is_set: true, locked: true, state: "env_secret_needs_env_url" }),
    });
    expect(screen.getByText(/Set the URL in the container too/)).toBeVisible();
  });

  it("a required secret is marked and explains why", async () => {
    await renderField({
      label: "API key",
      required: true,
      view: settingView("integrations.snipeit.api_key", "secret", { is_set: true }),
    });
    expect(screen.getByLabelText(/API key/)).toBeRequired();
    expect(screen.getByText(/saved for the old URL/)).toBeVisible();
  });

  it("a text field passes what is typed on", async () => {
    const { onChange } = await renderField({ label: "Name", view: settingView("general.display_name", "str", { value: "Hub" }), value: "" });
    await userEvent.type(screen.getByRole("textbox", { name: "Name" }), "A");
    expect(onChange).toHaveBeenCalledWith("A");
  });

  it("a boolean is a switch", async () => {
    const { onChange } = await renderField({ label: "Flag", value: false, view: settingView("x.flag", "bool", { value: false }) });
    await userEvent.click(screen.getByRole("switch", { name: "Flag" }));
    expect(onChange).toHaveBeenCalledWith(true);
  });
});
