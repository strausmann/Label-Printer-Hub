// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { I18nProvider } from "@lingui/react";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ComboBox, Input, Label, ListBox, ListBoxItem, Popover } from "react-aria-components";
import { describe, expect, it, vi } from "vitest";
import { i18n, initI18n } from "../../i18n";
import { ModalDialog } from "./controls";

async function open(props: Partial<React.ComponentProps<typeof ModalDialog>> = {}, lang: "en" | "de" = "en") {
  await initI18n(lang);
  const onClose = vi.fn();
  render(
    <I18nProvider i18n={i18n}>
      <ModalDialog title="A dialog" isOpen onClose={onClose} {...props}>
        {props.children ?? <p>Body</p>}
      </ModalDialog>
    </I18nProvider>,
  );
  const dialog = screen.getByRole(props.alert ? "alertdialog" : "dialog");
  // The dialog sits in the Modal box, which sits in the dim layer.
  const backdrop = dialog.parentElement!.parentElement!;
  return { onClose, dialog, backdrop };
}

describe("ModalDialog close button", () => {
  it("a dismissable dialog has one, named Close, and pressing it closes the dialog", async () => {
    const { onClose, dialog } = await open();
    const close = screen.getByRole("button", { name: "Close" });
    expect(dialog).toContainElement(close);
    await userEvent.click(close);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("is named Schließen in German", async () => {
    await open({}, "de");
    expect(screen.getByRole("button", { name: "Schließen" })).toBeVisible();
  });

  it("comes after the heading, so the title is read first", async () => {
    const { dialog } = await open();
    const heading = screen.getByRole("heading", { name: "A dialog" });
    const close = screen.getByRole("button", { name: "Close" });
    expect(heading.compareDocumentPosition(close) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(dialog).toHaveAccessibleName("A dialog");
  });

  it("an alert dialog has none: it is left through its own buttons", async () => {
    await open({ alert: true });
    expect(screen.queryByRole("button", { name: "Close" })).toBeNull();
  });

  it("a dialog that holds the only copy of something has none", async () => {
    await open({ dismissable: false });
    expect(screen.queryByRole("button", { name: "Close" })).toBeNull();
  });
});

describe("ModalDialog dim area (#318)", () => {
  it("a press on it closes a dismissable dialog once", async () => {
    const { onClose, backdrop } = await open();
    await userEvent.click(backdrop);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("a press that starts inside the dialog and ends on it does not close the dialog", async () => {
    const { onClose, dialog, backdrop } = await open();
    await userEvent.pointer([{ keys: "[MouseLeft>]", target: dialog }, { target: backdrop }, { keys: "[/MouseLeft]", target: backdrop }]);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("a press on it does not close an alert or a dialog that holds the only copy of something", async () => {
    for (const props of [{ alert: true }, { dismissable: false }]) {
      const { onClose, backdrop } = await open(props);
      await userEvent.click(backdrop);
      expect(onClose).not.toHaveBeenCalled();
      cleanup();
    }
  });

  it("closes the dialog while a combobox list inside it is open, and leaves the field alone", async () => {
    // The list of a combobox is a non-modal popover. React Aria closes only the top-most overlay on a press outside, and only
    // a dismissable one: the open list was the top-most and not dismissable, so the dialog stayed (#318).
    const field = (
      <ComboBox menuTrigger="focus" aria-label="Type">
        <Label>Type</Label>
        <Input />
        <Popover>
          <ListBox>
            <ListBoxItem id="a">Alpha</ListBoxItem>
            <ListBoxItem id="b">Beta</ListBoxItem>
          </ListBox>
        </Popover>
      </ComboBox>
    );
    const { onClose, backdrop } = await open({ children: field });
    const input = screen.getByRole("combobox");
    await userEvent.click(input);
    expect(await screen.findByRole("listbox")).toBeVisible();
    await userEvent.click(backdrop);
    expect(onClose).toHaveBeenCalledTimes(1);
    // The press kept the focus where it was: the field was not given it again, so its list (and a phone's keyboard) did not reopen.
    expect(input).toHaveFocus();
  });
});
