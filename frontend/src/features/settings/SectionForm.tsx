import { useLingui } from "@lingui/react/macro";
import { useState } from "react";
import { Button } from "react-aria-components";
import { PRIMARY_BUTTON } from "../../shell/SignIn";
import { useSaveSettings, type SettingView } from "./api";
import { useSettingsDraft } from "./draft";
import { SaveFeedback, useErrorText } from "./feedback";
import { SettingField } from "./SettingField";

export interface FieldSpec {
  key: string;
  label: string;
  description?: string;
  choiceLabels?: Record<string, string>;
}

/** A plain settings form: some fields, one Save that sends only what changed. */
export function SectionForm({ views, fields }: { views: SettingView[]; fields: FieldSpec[] }) {
  const { t } = useLingui();
  const errorText = useErrorText();
  const draft = useSettingsDraft(views);
  const save = useSaveSettings();
  const [saved, setSaved] = useState(false);
  const keys = fields.map((f) => f.key);
  const { values, invalid } = draft.payload(keys);
  const dirty = Object.keys(values).length > 0 || invalid.length > 0;

  return (
    <form
      className="flex max-w-xl flex-col gap-5"
      onSubmit={(event) => {
        event.preventDefault();
        setSaved(false);
        save.mutate(values, {
          onSuccess: () => {
            draft.clear(keys);
            setSaved(true);
          },
        });
      }}
    >
      {fields.map((field) => {
        const view = views.find((v) => v.key === field.key);
        if (!view) return null;
        return (
          <SettingField
            key={field.key}
            view={view}
            label={field.label}
            description={field.description}
            choiceLabels={field.choiceLabels}
            value={draft.valueOf(field.key)}
            onChange={(value) => {
              setSaved(false);
              draft.set(field.key, value);
            }}
          />
        );
      })}
      <div className="flex flex-col gap-2">
        <div>
          <Button type="submit" isDisabled={!dirty || invalid.length > 0 || save.isPending} className={PRIMARY_BUTTON}>
            {t`Save`}
          </Button>
        </div>
        <SaveFeedback error={save.isError ? errorText(save.error) : invalid.length > 0 ? t`Enter a valid number.` : null} saved={saved} />
      </div>
    </form>
  );
}
