// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useLingui } from "@lingui/react/macro";
import { useCallback, useEffect, useRef, type ReactNode } from "react";
import {
  Button,
  Checkbox,
  CheckboxGroup,
  Dialog,
  Heading,
  Input,
  Label,
  ListBox,
  ListBoxItem,
  Modal,
  ModalOverlay,
  Popover,
  Select,
  SelectValue,
  Switch,
  Text,
  TextField,
} from "react-aria-components";
import { FIELD } from "../../shell/SignIn";

const FOCUS =
  "data-[focus-visible]:outline-3 data-[focus-visible]:outline-offset-2 data-[focus-visible]:outline-link";

export const FIELD_READONLY = `${FIELD} data-[readonly]:bg-surface data-[readonly]:text-ink-2`;
export const LABEL = "text-small font-bold text-ink";
export const HINT = "text-small text-ink-2";

/** A labelled text input; the description is tied to it for screen readers. */
export function TextInput({
  label,
  value,
  onChange,
  type = "text",
  readOnly,
  placeholder,
  description,
  required,
  invalid,
  mono,
  autoComplete,
  inputMode,
  hideLabel,
  maxLength,
  validationBehavior,
}: {
  label: string;
  value: string;
  onChange?: (value: string) => void;
  type?: "text" | "url" | "password" | "number";
  readOnly?: boolean;
  placeholder?: string;
  description?: ReactNode;
  required?: boolean;
  invalid?: boolean;
  mono?: boolean;
  autoComplete?: string;
  inputMode?: "numeric" | "decimal" | "url" | "text";
  hideLabel?: boolean;
  maxLength?: number;
  /**
   * `aria` marks the field invalid for assistive technology only. The default (`native`) also sets a custom validity, so
   * the browser blocks the submit before the form's own check can say what is wrong.
   */
  validationBehavior?: "aria" | "native";
}) {
  return (
    <TextField
      validationBehavior={validationBehavior}
      value={value}
      onChange={onChange}
      isReadOnly={readOnly}
      isRequired={required}
      isInvalid={invalid}
      type={type === "number" ? "text" : type}
      autoComplete={autoComplete}
      maxLength={maxLength}
      className="flex min-w-0 flex-col gap-1.5"
    >
      <Label className={hideLabel ? "sr-only" : LABEL}>{label}</Label>
      <Input
        placeholder={placeholder}
        inputMode={inputMode}
        spellCheck={false}
        className={`${readOnly ? FIELD_READONLY : FIELD} data-[invalid]:border-bad ${mono ? "font-mono" : ""}`}
      />
      {description ? (
        <Text slot="description" className={HINT}>
          {description}
        </Text>
      ) : null}
    </TextField>
  );
}

/** A switch with its label on the right; the track is the only decoration. */
export function SwitchField({
  label,
  isSelected,
  onChange,
  isDisabled,
  description,
}: {
  label: string;
  isSelected: boolean;
  onChange?: (value: boolean) => void;
  isDisabled?: boolean;
  description?: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1">
      <Switch
        isSelected={isSelected}
        onChange={onChange}
        isDisabled={isDisabled}
        className={`group flex min-h-11 items-center gap-3 data-[disabled]:opacity-60 ${FOCUS} rounded-r2`}
      >
        <span
          aria-hidden="true"
          className="flex h-6 w-11 shrink-0 items-center rounded-full bg-line-strong px-0.5 transition-colors duration-150 group-data-[selected]:bg-accent"
        >
          <span className="size-5 rounded-full bg-surface transition-transform duration-150 ease-out group-data-[selected]:translate-x-5" />
        </span>
        <span className="font-bold text-ink">{label}</span>
      </Switch>
      {description ? <p className={`${HINT} pl-14`}>{description}</p> : null}
    </div>
  );
}

export interface Option {
  id: string;
  label: string;
}

/** The shared select: React Aria's listbox in a popover, never a native `<select>`. */
export function SelectField({
  label,
  value,
  options,
  onChange,
  isDisabled,
}: {
  label: string;
  value: string;
  options: Option[];
  onChange: (id: string) => void;
  isDisabled?: boolean;
}) {
  return (
    <Select
      selectedKey={value}
      onSelectionChange={(key) => onChange(String(key))}
      isDisabled={isDisabled}
      className="flex min-w-0 flex-col gap-1.5"
    >
      <Label className={LABEL}>{label}</Label>
      <Button
        className={`press flex h-11 w-full items-center justify-between gap-2 rounded-r2 border border-line-strong bg-sunken px-3 text-left text-ink data-[disabled]:opacity-60 ${FOCUS}`}
      >
        {/* One line, cut at the end: a long value (a 64-character key) must not outgrow the 44 px button. The list shows it in full. */}
        {/* The title keeps the full text reachable when the value is cut. */}
        <span title={options.find((o) => o.id === value)?.label} className="min-w-0 truncate">
          <SelectValue />
        </span>
        <svg viewBox="0 0 12 12" width="12" height="12" aria-hidden="true" className="shrink-0 fill-none stroke-current stroke-2">
          <path d="M2 4.5 6 8.5 10 4.5" />
        </svg>
      </Button>
      <Popover className="flex w-(--trigger-width) origin-(--trigger-anchor-point) flex-col rounded-r2 border border-line-strong bg-surface p-1 shadow-lg data-[entering]:animate-[fadein_140ms_cubic-bezier(0.23,1,0.32,1)]">
        {/* The popover is as tall as the room beside the trigger (it sets max-height); a long list scrolls inside it instead of covering the trigger. */}
        <ListBox className="max-h-[inherit] overflow-y-auto overscroll-contain outline-none">
          {options.map((option) => (
            <ListBoxItem
              key={option.id}
              id={option.id}
              textValue={option.label}
              className="flex min-h-11 cursor-default items-center rounded-r1 px-3 text-ink outline-none data-[focused]:bg-sunken data-[selected]:font-bold"
            >
              {option.label}
            </ListBoxItem>
          ))}
        </ListBox>
      </Popover>
    </Select>
  );
}

/** Checkboxes for a set of values (key scopes). */
export function CheckboxChoices({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string[];
  options: Option[];
  onChange: (value: string[]) => void;
}) {
  return (
    <CheckboxGroup value={value} onChange={onChange} className="flex flex-col gap-1.5">
      <Label className={LABEL}>{label}</Label>
      <div className="flex flex-wrap gap-x-5 gap-y-1">
        {options.map((option) => (
          <Checkbox key={option.id} value={option.id} className={`group flex min-h-11 items-center gap-2 ${FOCUS} rounded-r1`}>
            <span
              aria-hidden="true"
              className="flex size-5 shrink-0 items-center justify-center rounded-r1 border border-line-strong bg-sunken group-data-[selected]:border-accent group-data-[selected]:bg-accent"
            >
              <svg viewBox="0 0 12 12" width="12" height="12" className="fill-none stroke-accent-ink stroke-2 opacity-0 group-data-[selected]:opacity-100">
                <path d="M2.5 6.5 5 9l4.5-5.5" />
              </svg>
            </span>
            <span>{option.label}</span>
          </Checkbox>
        ))}
      </div>
    </CheckboxGroup>
  );
}

/**
 * A press that starts and ends on the dimmed area around a dialog closes it, whatever is open inside the dialog (#318).
 *
 * React Aria closes only the top-most overlay on a press outside, and only when that overlay is dismissable. The open list of
 * a combobox is a non-modal popover: it is the top-most overlay but not a dismissable one, so the dialog ignored the press.
 * The press still moved the focus to the page, the dialog's focus scope put it back into the field, the field opened its
 * list again and a phone its keyboard: every tap on the dim area ended where it started. This listens on the dim layer
 * itself, so the stack of overlays has no say, and keeps the focus where it is until the dialog is gone.
 */
function useBackdropClose(enabled: boolean, onClose: () => void) {
  const latest = useRef(onClose);
  useEffect(() => {
    latest.current = onClose;
  });
  return useCallback(
    (layer: HTMLDivElement | null) => {
      if (!layer || !enabled) return;
      let started = false;
      const down = (event: PointerEvent) => {
        // On the layer itself, not on the dialog or anything inside it.
        started = event.target === layer && event.isPrimary && event.button === 0;
        // No focus move: the browser would take the focus to the page, and the dialog would hand it back to the field.
        if (started) event.preventDefault();
      };
      const up = (event: PointerEvent) => {
        if (started && event.target === layer) latest.current();
        started = false;
      };
      // A touch that turns into a scroll is cancelled, not released: it does not close the dialog.
      const cancel = () => {
        started = false;
      };
      layer.addEventListener("pointerdown", down);
      layer.addEventListener("pointerup", up);
      layer.addEventListener("pointercancel", cancel);
      return () => {
        layer.removeEventListener("pointerdown", down);
        layer.removeEventListener("pointerup", up);
        layer.removeEventListener("pointercancel", cancel);
      };
    },
    [enabled],
  );
}

/**
 * A modal dialog with a heading; `alert` makes it an alertdialog (confirmations).
 * A dismissable dialog has a close button in its top-right corner and closes on Escape and on a press on the dim area;
 * an alert dialog and a dialog that holds the only copy of something are left only through their own buttons.
 */
export function ModalDialog({
  title,
  children,
  isOpen,
  onClose,
  alert,
  dismissable = !alert,
  wide,
}: {
  title: string;
  children: ReactNode;
  isOpen: boolean;
  onClose: () => void;
  alert?: boolean;
  /** Escape, the close button and a press on the dim area close it; off for a dialog that holds the only copy of something. */
  dismissable?: boolean;
  /** A form-sized dialog: wider. Every dialog scrolls inside itself when the visible area (screen minus keyboard) is too short. */
  wide?: boolean;
}) {
  const { t } = useLingui();
  const closeButton = dismissable && !alert;
  const backdrop = useBackdropClose(dismissable, onClose);
  return (
    <ModalOverlay
      ref={backdrop}
      isOpen={isOpen}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      // The dim area is handled by useBackdropClose; React Aria's own outside press would close the dialog a second time.
      isDismissable={false}
      isKeyboardDismissDisabled={!dismissable}
      // The overlay is the visible area, not the screen: with the on-screen keyboard open the dialog centres above it.
      className="fixed inset-x-0 top-(--vv-top) z-50 grid h-(--vvh) place-items-center bg-ink/40 p-4 data-[entering]:animate-[fadein_160ms_ease-out]"
    >
      <Modal
        className={`max-h-[calc(var(--vvh)-2rem)] w-full overflow-y-auto overscroll-contain rounded-r3 border border-line bg-surface data-[entering]:animate-[popin_180ms_cubic-bezier(0.23,1,0.32,1)] ${
          wide ? "max-w-3xl p-4 sm:p-6" : "max-w-md p-6"
        }`}
      >
        <Dialog role={alert ? "alertdialog" : "dialog"} className="flex flex-col gap-4 outline-none">
          <div className="flex items-start gap-2">
            <Heading slot="title" className="min-w-0 flex-1 text-section font-bold [overflow-wrap:anywhere]">
              {title}
            </Heading>
            {closeButton ? (
              // 44 px to hit; pulled into the corner so the heading keeps its line and the dialog its padding.
              <Button
                slot="close"
                aria-label={t`Close`}
                className={`press -mt-2.5 -mr-2.5 flex size-11 shrink-0 items-center justify-center rounded-r2 text-ink-2 data-[hovered]:bg-sunken data-[hovered]:text-ink data-[pressed]:bg-sunken ${FOCUS}`}
              >
                <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" className="fill-none stroke-current stroke-2 [stroke-linecap:round]">
                  <path d="M3.5 3.5 12.5 12.5M12.5 3.5 3.5 12.5" />
                </svg>
              </Button>
            ) : null}
          </div>
          {children}
        </Dialog>
      </Modal>
    </ModalOverlay>
  );
}
