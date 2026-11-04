import { useLingui } from "@lingui/react/macro";
import { Button } from "react-aria-components";
import { StatusBadge } from "../../shell/StatusBadge";
import { SECONDARY_BUTTON } from "../ui";
import type { SettingView } from "./api";
import { HINT, LABEL, SelectField, SwitchField, TextInput } from "./controls";
import type { DraftValue } from "./draft";

interface Props {
  view: SettingView;
  label: string;
  /** What the form currently holds; a secret's value is only what was typed in this session. */
  value: DraftValue;
  onChange: (value: DraftValue) => void;
  description?: string;
  /** The secret must be entered again in this save (it is bound to the URL it was saved with). */
  required?: boolean;
  /** Labels for enum choices, by value. */
  choiceLabels?: Record<string, string>;
  mono?: boolean;
}

/**
 * One setting as a form control. Locked values (D4) are shown read-only with the reason;
 * secrets (D5) are write-only: the field starts empty and says whether a value is saved.
 */
export function SettingField({ view, label, value, onChange, description, required, choiceLabels, mono }: Props) {
  const { t } = useLingui();
  const locked = view.locked;
  const lockedHint = t`Set by the container`;

  let warning: string | null = null;
  if (view.state === "undecryptable") warning = t`Can't be read with the current secret key — enter it again`;
  if (view.state === "env_secret_needs_env_url") {
    warning = t`The secret comes from the container, but the URL does not. Set the URL in the container too.`;
  }
  const badge = warning ? <StatusBadge state="warn" label={warning} /> : null;

  if (view.kind === "secret") {
    if (locked) {
      return (
        <div className="flex flex-col gap-1.5">
          <span className={LABEL}>{label}</span>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
            <StatusBadge state={view.is_set ? "ok" : "idle"} label={view.is_set ? t`Set` : t`Not set`} />
            <span className={HINT}>{lockedHint}</span>
          </div>
          {badge}
        </div>
      );
    }
    const typed = typeof value === "string" ? value : "";
    const removing = value === null;
    const placeholder =
      view.state === "undecryptable" ? t`Enter it again` : view.is_set ? t`Saved — enter a new value to replace` : t`Not set`;
    const reason = required ? t`This secret is saved for the old URL. Enter it again to use the new URL.` : description;
    return (
      <div className="flex flex-col gap-2">
        <TextInput
          label={label}
          value={typed}
          onChange={onChange}
          type="password"
          autoComplete="new-password"
          placeholder={removing ? t`Will be removed when you save` : placeholder}
          description={reason}
          required={required}
          invalid={required && typed === ""}
          mono={mono}
        />
        {badge}
        {view.is_set && !removing && view.state === "ok" ? (
          <Button onPress={() => onChange(null)} className={`${SECONDARY_BUTTON} self-start`}>
            {t`Remove saved value`}
          </Button>
        ) : null}
        {removing ? (
          <Button onPress={() => onChange("")} className={`${SECONDARY_BUTTON} self-start`}>
            {t`Keep saved value`}
          </Button>
        ) : null}
      </div>
    );
  }

  if (view.kind === "bool") {
    return (
      <SwitchField
        label={label}
        isSelected={Boolean(value)}
        onChange={onChange}
        isDisabled={locked}
        description={locked ? lockedHint : description}
      />
    );
  }

  if (view.kind === "enum" && !locked) {
    return (
      <SelectField
        label={label}
        value={String(value)}
        options={view.choices?.map((c) => ({ id: c, label: choiceLabels?.[c] ?? c })) ?? []}
        onChange={onChange}
      />
    );
  }

  const text = String(value ?? "");
  const numeric = view.kind === "int" || view.kind === "float";
  return (
    <TextInput
      label={label}
      value={locked && view.kind === "enum" ? (choiceLabels?.[text] ?? text) : text}
      onChange={locked ? undefined : (v) => onChange(v)}
      type={view.kind === "url" ? "url" : "text"}
      readOnly={locked}
      description={locked ? lockedHint : description}
      inputMode={numeric ? (view.kind === "int" ? "numeric" : "decimal") : view.kind === "url" ? "url" : undefined}
      mono={mono ?? view.kind === "url"}
    />
  );
}
