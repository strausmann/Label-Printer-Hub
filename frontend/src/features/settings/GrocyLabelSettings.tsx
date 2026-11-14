// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { Trans, useLingui } from "@lingui/react/macro";
import { Link } from "@tanstack/react-router";
import { useState } from "react";
import { Button } from "react-aria-components";
import { PRIMARY_BUTTON } from "../../shell/SignIn";
import { StatusBadge } from "../../shell/StatusBadge";
import { useContentTypeLabel } from "../lookup/apps";
import type { ContentType } from "../lookup/cart";
import { PANEL, SECONDARY_BUTTON } from "../ui";
import { useAdminPrinters, useSaveSettings, type SettingView } from "./api";
import { HINT, SelectField } from "./controls";
import { useSettingsDraft, type DraftValue } from "./draft";
import { SaveFeedback, useErrorText } from "./feedback";
import {
  GROCY_LABEL_DEFAULT_PRINTER_KEY,
  GROCY_LABEL_ENABLED_KEY,
  GROCY_LABEL_TYPES,
  grocyConfigBlock,
  grocyContentTypeKey,
  grocyLabelKeys,
  grocyPrinterKey,
  labelPrinterOptions,
  type GrocyLabelType,
  type LabelPrinter,
} from "./grocyLabel";
import { SettingField } from "./SettingField";

function useTypeName(): (type: GrocyLabelType) => string {
  const { t } = useLingui();
  return (type) => ({ product: t`Product`, stock_entry: t`Stock entry`, chore: t`Chore`, battery: t`Battery`, recipe: t`Recipe` })[type];
}

/**
 * Where a label goes. Only a printer today; a page printer brings a sheet type next to it (#281, Task 8b), so a target
 * is its own block that can grow a second control.
 */
function LabelTarget({
  label,
  value,
  printers,
  emptyLabel,
  onChange,
  isDisabled,
}: {
  label: string;
  value: string;
  /** `null` while the printers are not known (loading or failed). */
  printers: readonly LabelPrinter[] | null;
  emptyLabel: string;
  onChange: (value: string) => void;
  isDisabled?: boolean;
}) {
  const { t } = useLingui();
  const options = labelPrinterOptions(printers, value, emptyLabel, (slug) => t`${slug} (not available)`);
  return (
    <div className="flex min-w-0 flex-col gap-3">
      <SelectField label={label} value={value} options={options} onChange={onChange} isDisabled={isDisabled} />
    </div>
  );
}

function ConfigBlock({ publicUrl }: { publicUrl: string }) {
  const { t } = useLingui();
  const [copy, setCopy] = useState<"idle" | "done" | "failed">("idle");
  const block = grocyConfigBlock(publicUrl);
  async function copyBlock() {
    try {
      await navigator.clipboard.writeText(block);
      setCopy("done");
    } catch {
      setCopy("failed");
    }
  }
  return (
    <div role="group" aria-labelledby="grocy-config-heading" className="flex min-w-0 flex-col gap-3">
      <h4 id="grocy-config-heading" className="font-bold">
        {t`In Grocy's config.php`}
      </h4>
      <p className="max-w-prose text-ink">
        <Trans>
          Add these lines to Grocy's <code className="font-mono">data/config.php</code> and replace{" "}
          <code className="font-mono">&lt;print-key&gt;</code> with an API key of this hub.
        </Trans>
      </p>
      {publicUrl.trim() === "" ? (
        <p className={HINT}>{t`No public URL is set for this hub, so the address starts with <public-url>. Set LABELYARD_PUBLIC_URL in the container.`}</p>
      ) : null}
      {/* A long line scrolls inside the block; the keyboard reaches it to scroll it. */}
      {/* eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex */}
      <pre role="region" tabIndex={0} aria-label={t`Lines for Grocy's config.php`} className="max-w-full overflow-x-auto rounded-r2 bg-sunken p-3 font-mono text-small text-ink">
        <code>{block}</code>
      </pre>
      <div className="flex flex-wrap items-center gap-3">
        <Button onPress={() => void copyBlock()} className={SECONDARY_BUTTON}>
          {t`Copy lines`}
        </Button>
        <span role="status" className="text-small text-ink-2">
          {copy === "done" ? t`Copied` : copy === "failed" ? t`Copy failed. Select the lines and copy them by hand.` : ""}
        </span>
      </div>
      <div className="flex max-w-prose flex-col gap-2 rounded-r2 bg-sunken p-3">
        <StatusBadge state="warn" label={t`About the key`} />
        <p className="text-ink">
          {t`Use a key with the print scope, restricted to the label printer. Grocy writes the address with the key to its own log, and shows it to the Grocy user when the hub refuses a label or does not answer within 2 seconds.`}
        </p>
        <p className="text-ink">
          <Trans>
            Create the key under{" "}
            <Link to="/settings/access" className="text-link underline underline-offset-2">
              Access and keys
            </Link>
            .
          </Trans>
        </p>
      </div>
    </div>
  );
}

/** Grocy's own labels (#281): the switch, the default target and a layout and target per label type, saved together. */
export function GrocyLabelSettings({ views }: { views: SettingView[] }) {
  const { t } = useLingui();
  const errorText = useErrorText();
  const draft = useSettingsDraft(views);
  const save = useSaveSettings();
  const printers = useAdminPrinters();
  const typeName = useTypeName();
  const contentTypeLabel = useContentTypeLabel();
  const [saved, setSaved] = useState(false);

  const enabledView = draft.view(GROCY_LABEL_ENABLED_KEY);
  if (!enabledView) return null;

  const keys = grocyLabelKeys();
  const { values, invalid } = draft.payload(keys);
  const changed = Object.keys(values).length > 0;
  // Until the list has arrived nothing says a saved printer is unavailable, so it is shown as it is.
  const list: readonly LabelPrinter[] | null = printers.isSuccess ? printers.data : null;
  const enabled = Boolean(enabledView.value);
  const publicUrl = String(draft.view("general.public_url")?.value ?? "");

  const change = (key: string) => (value: DraftValue) => {
    setSaved(false);
    draft.set(key, value);
  };
  const locked = (key: string) => Boolean(draft.view(key)?.locked);

  return (
    <div role="group" aria-labelledby="grocy-label-heading" className={`${PANEL} flex flex-col gap-6`}>
      <div className="flex flex-col gap-1">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 id="grocy-label-heading" className="text-section font-bold">
            {t`Grocy labels`}
          </h3>
          <StatusBadge state={enabled ? "ok" : "idle"} label={enabled ? t`On` : t`Off`} />
        </div>
        <p className="max-w-prose text-ink-2">
          {t`Grocy can send its own labels to this hub: products, stock entries, chores, batteries and recipes. Each label becomes a print job on the printer you choose here.`}
        </p>
      </div>

      <div className="grid max-w-xl gap-5">
        <SettingField
          view={enabledView}
          label={t`Print Grocy's labels`}
          value={draft.valueOf(GROCY_LABEL_ENABLED_KEY)}
          onChange={change(GROCY_LABEL_ENABLED_KEY)}
          description={t`While this is off, the hub refuses labels from Grocy.`}
        />
        <LabelTarget
          label={t`Default printer`}
          value={String(draft.valueOf(GROCY_LABEL_DEFAULT_PRINTER_KEY))}
          printers={list}
          emptyLabel={t`First enabled tape printer`}
          onChange={change(GROCY_LABEL_DEFAULT_PRINTER_KEY)}
          isDisabled={locked(GROCY_LABEL_DEFAULT_PRINTER_KEY)}
        />
        {printers.isError ? <p className={HINT}>{t`The printers could not be loaded. A saved printer is shown by its short name.`}</p> : null}
      </div>

      <div className="flex flex-col gap-3">
        <h4 className="font-bold">{t`Per label type`}</h4>
        <ul className="grid gap-3">
          {GROCY_LABEL_TYPES.map((type) => {
            const contentKey = grocyContentTypeKey(type);
            const printerKey = grocyPrinterKey(type);
            const contentView = draft.view(contentKey);
            const heading = `grocy-label-${type}`;
            return (
              <li key={type} role="group" aria-labelledby={heading} className="grid gap-4 rounded-r2 bg-sunken p-3 md:grid-cols-[8rem_1fr_1fr] md:items-end">
                <span id={heading} className="font-bold md:pb-3">
                  {typeName(type)}
                </span>
                {contentView ? (
                  <SelectField
                    label={t`Layout`}
                    value={String(draft.valueOf(contentKey))}
                    options={(contentView.choices ?? []).map((c) => ({ id: c, label: contentTypeLabel(c as ContentType) }))}
                    onChange={change(contentKey)}
                    isDisabled={contentView.locked}
                  />
                ) : null}
                <LabelTarget
                  label={t`Printer`}
                  value={String(draft.valueOf(printerKey))}
                  printers={list}
                  emptyLabel={t`Same as default`}
                  onChange={change(printerKey)}
                  isDisabled={locked(printerKey)}
                />
              </li>
            );
          })}
        </ul>
        <p className={`${HINT} max-w-prose`}>
          {t`The layout with a detail line needs a second line from Grocy. Grocy sends one only for a stock entry with a due date; other labels print without the detail line.`}
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <Button
          isDisabled={!changed || invalid.length > 0 || save.isPending}
          onPress={() => {
            setSaved(false);
            // Only what this save sent is settled by it; an edit made while it is on its way stays in the draft.
            const sent = Object.keys(values);
            save.mutate(values, {
              onSuccess: () => {
                draft.clear(sent);
                setSaved(true);
              },
            });
          }}
          className={PRIMARY_BUTTON}
        >
          {t`Save`}
        </Button>
        <SaveFeedback error={save.isError ? errorText(save.error) : null} saved={saved} />
      </div>

      <ConfigBlock publicUrl={publicUrl} />
    </div>
  );
}
