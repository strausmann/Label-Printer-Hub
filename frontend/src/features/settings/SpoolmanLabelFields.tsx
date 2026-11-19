// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useLingui } from "@lingui/react/macro";
import { Button, Disclosure, DisclosurePanel, Heading } from "react-aria-components";
import { HINT } from "./controls";
import type { useSettingsDraft } from "./draft";
import { SettingField } from "./SettingField";

const PREFIX = "integrations.spoolman.label.";
const KEY_FIELDS = ["nozzle_field", "pressure_advance_field", "flow_ratio_field", "drying_temp_field", "drying_time_field"] as const;
const TITLE_SOURCE = `${PREFIX}title_source`;

/** The six settings of the spool label (#346): saved with the Spoolman card, not part of its connection test. */
export const SPOOLMAN_LABEL_KEYS: readonly string[] = [...KEY_FIELDS.map((f) => `${PREFIX}${f}`), TITLE_SOURCE];

/**
 * Which Spoolman extra fields the spool label reads, and what its black bar shows. Collapsed by default: the
 * defaults match Spoolman's own field names, so most people never open it. Edits go into the card's draft and
 * are saved with the card.
 */
export function SpoolmanLabelFields({ draft }: { draft: ReturnType<typeof useSettingsDraft> }) {
  const { t } = useLingui();
  const labels: Record<(typeof KEY_FIELDS)[number], string> = {
    nozzle_field: t`Nozzle temperature field`,
    pressure_advance_field: t`Pressure advance field`,
    flow_ratio_field: t`Flow ratio field`,
    drying_temp_field: t`Drying temperature field`,
    drying_time_field: t`Drying time field`,
  };
  const titleView = draft.view(TITLE_SOURCE);
  return (
    <Disclosure className="rounded-r2 bg-sunken">
      <Heading level={4} className="m-0">
        <Button
          slot="trigger"
          className="press group flex min-h-11 w-full items-center justify-between gap-3 rounded-r2 px-3 py-2 text-left font-bold text-ink data-[focus-visible]:outline-3 data-[focus-visible]:outline-offset-2 data-[focus-visible]:outline-link"
        >
          <span>{t`Label fields`}</span>
          <svg
            aria-hidden="true"
            viewBox="0 0 12 12"
            className="size-3 shrink-0 transition-transform duration-200 ease-out group-aria-expanded:rotate-90 motion-reduce:transition-none"
          >
            <path d="M4 1.5 8.5 6 4 10.5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </Button>
      </Heading>
      <DisclosurePanel className="h-(--disclosure-panel-height) overflow-clip transition-[height] duration-200 ease-out motion-reduce:transition-none">
        <div className="grid gap-5 px-3 pt-1 pb-4">
          <p className={`${HINT} m-0`}>{t`Keys of the extra fields in your Spoolman.`}</p>
          {KEY_FIELDS.map((field) => {
            const key = `${PREFIX}${field}`;
            const view = draft.view(key);
            return view ? (
              <SettingField key={key} view={view} label={labels[field]} value={draft.valueOf(key)} onChange={(v) => draft.set(key, v)} mono />
            ) : null;
          })}
          {titleView ? (
            <SettingField
              view={titleView}
              label={t`Bar shows`}
              value={draft.valueOf(TITLE_SOURCE)}
              onChange={(v) => draft.set(TITLE_SOURCE, v)}
              choiceLabels={{ material: t`Material`, name: t`Filament name` }}
            />
          ) : null}
        </div>
      </DisclosurePanel>
    </Disclosure>
  );
}
