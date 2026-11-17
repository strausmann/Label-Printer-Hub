// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useLingui } from "@lingui/react/macro";
import { useState } from "react";
import { Button, Radio, RadioGroup } from "react-aria-components";
import { HINT, SelectField } from "../settings/controls";
import { formatMm, pageSizeMm } from "../sheets/cellState";
import { LinerPreview } from "../sheets/backSide/LinerPreview";
import { marginPossible, placeStrip, widestMargin } from "../sheets/backSide/strip";
import { PANEL, PRIMARY_BUTTON, SECONDARY_BUTTON } from "../ui";
import { useBackingDesigns, usePatchType, type SheetTypeDetail } from "./api";
import { useArchiveErrorText } from "./errors";

type Choice = "margin" | "back_side" | "cell";
const PLAIN = "";

/** Cell 1 says where it is; the rest are numbers (a 400-cell type lists 400 of them). */
export function cellOptions(total: number, firstWord: string): { id: string; label: string }[] {
  return Array.from({ length: total }, (_, i) => ({ id: String(i + 1), label: i === 0 ? firstWord : String(i + 1) }));
}

const OPTION =
  "group flex min-h-11 cursor-pointer flex-col gap-1 rounded-r3 border border-line bg-surface p-4 transition-colors duration-150 data-[selected]:border-accent data-[selected]:bg-accent-soft/40 data-[disabled]:cursor-not-allowed data-[disabled]:border-dashed data-[disabled]:bg-sunken data-[focus-visible]:outline-3 data-[focus-visible]:outline-offset-2 data-[focus-visible]:outline-link";

function Dot() {
  return (
    <span aria-hidden="true" className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full border-2 border-line-strong bg-sunken group-data-[selected]:border-accent">
      <span className="size-2.5 scale-0 rounded-full bg-accent transition-transform duration-150 ease-out group-data-[selected]:scale-100" />
    </span>
  );
}

/**
 * "Where the code goes" of a sheet type (#350, mockup 350-1): margin, back side or a reserved cell, the
 * cell number, and the backing design the back preview is drawn from. `auto` shows the option it resolves
 * to, with the note that it was chosen automatically; saving the automatic option keeps `auto`.
 */
export function IdPlacementSection({ type, admin }: { type: SheetTypeDetail; admin: boolean }) {
  const { t, i18n } = useLingui();
  const errorText = useArchiveErrorText();
  const patch = usePatchType();
  const designs = useBackingDesigns();
  const g = type.geometry;
  const total = g.cols * g.rows;
  const marginOk = marginPossible(g);
  const automatic: Choice = marginOk ? "margin" : "back_side";
  const stored: Choice = type.id_placement === "auto" ? automatic : type.id_placement;
  const [choice, setChoice] = useState<Choice>(stored);
  const [cell, setCell] = useState(String(type.id_cell ?? 1));
  const [design, setDesign] = useState(type.backing_design?.key ?? PLAIN);
  const [saved, setSaved] = useState(false);

  const sameSize = (designs.data ?? []).filter((d) => d.page_size === g.page_size);
  const chosenDesign = sameSize.find((d) => d.key === design) ?? (design === type.backing_design?.key ? type.backing_design : null);
  const strips = chosenDesign?.strips ?? [];
  const where = placeStrip(strips);
  const widest = formatMm(Math.max(0, widestMargin(g)), i18n.locale);
  const dirty = choice !== stored || (choice === "cell" && cell !== String(type.id_cell ?? 1)) || design !== (type.backing_design?.key ?? PLAIN);

  function save() {
    const setting = choice === automatic && type.id_placement === "auto" ? "auto" : choice;
    patch.mutate(
      {
        key: type.key,
        patch: {
          id_placement: setting,
          ...(choice === "cell" ? { id_cell: Number(cell) } : {}),
          backing_design: design === PLAIN ? null : design,
        },
      },
      { onSuccess: () => setSaved(true) },
    );
  }
  function reset() {
    setChoice(stored);
    setCell(String(type.id_cell ?? 1));
    setDesign(type.backing_design?.key ?? PLAIN);
  }

  return (
    <div className="grid min-w-0 gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,18rem)]">
      <section aria-labelledby="placement-h" className="flex min-w-0 flex-col gap-4">
        <div className="flex flex-col gap-1">
          <h3 id="placement-h" className="text-section font-bold">{t`Where the sheet code goes`}</h3>
          <p className="text-ink-2">{t`The sheet code identifies a sheet when you scan it. Choose where the hub prints it.`}</p>
        </div>
        <RadioGroup
          aria-labelledby="placement-h"
          value={choice}
          onChange={(v) => {
            setChoice(v as Choice);
            setSaved(false);
          }}
          isReadOnly={!admin}
          className="flex flex-col gap-3"
        >
          <Radio value="margin" isDisabled={!marginOk} className={OPTION}>
            <span className="flex items-start gap-3">
              <Dot />
              <span className="flex min-w-0 flex-col gap-1">
                <span className="flex flex-wrap items-center gap-2 font-bold">
                  {t`Margin`}
                  {automatic === "margin" ? <DefaultBadge /> : null}
                </span>
                <span className="text-ink-2">{t`Prints the code in the free band around the labels. No extra pass through the printer.`}</span>
                {!marginOk ? (
                  <span className="rounded-r2 bg-sunken p-2 text-small text-warn">
                    {t`Not available for this sheet: no margin is wide enough for the code (the widest is ${widest}).`}
                  </span>
                ) : null}
              </span>
            </span>
          </Radio>
          <Radio value="back_side" className={OPTION}>
            <span className="flex items-start gap-3">
              <Dot />
              <span className="flex min-w-0 flex-col gap-1">
                <span className="flex flex-wrap items-center gap-2 font-bold">
                  {t`Back side`}
                  {automatic === "back_side" ? <DefaultBadge /> : null}
                </span>
                <span className="text-ink-2">
                  {t`When you activate a new sheet, the hub asks you to turn it over and prints the code on the back of the liner. One extra pass through the printer.`}
                </span>
              </span>
            </span>
          </Radio>
          <Radio value="cell" className={OPTION}>
            <span className="flex items-start gap-3">
              <Dot />
              <span className="flex min-w-0 flex-col gap-1">
                <span className="font-bold">{t`Reserved cell`}</span>
                <span className="text-ink-2">
                  {t`No second pass. One cell holds the code and cannot take a label.`}
                </span>
              </span>
            </span>
          </Radio>
        </RadioGroup>
        {choice === "cell" ? (
          <div className="flex max-w-xs flex-col gap-1">
            <SelectField label={t`Cell`} value={cell} options={cellOptions(total, t`1 (top left)`)} onChange={setCell} isDisabled={!admin} />
            <p className={HINT}>{t`Choose any cell. It is left out of planning.`}</p>
          </div>
        ) : null}
        {type.id_placement === "auto" ? (
          <p className="text-small text-ink-2">{t`Chosen automatically from the usable margin. You can change it.`}</p>
        ) : null}
        <div className="flex max-w-sm flex-col gap-1">
          <SelectField
            label={t`Print on the back of the liner`}
            value={design}
            options={[{ id: PLAIN, label: t`Plain liner` }, ...sameSize.map((d) => ({ id: d.key, label: d.name }))]}
            onChange={(v) => {
              setDesign(v);
              setSaved(false);
            }}
            isDisabled={!admin}
          />
          <p className={HINT}>{t`The free strips of the print decide where the code goes on the back.`}</p>
        </div>
        {admin ? (
          <div className="flex flex-wrap items-center gap-3 border-t border-line pt-4">
            <Button onPress={save} isDisabled={!dirty || patch.isPending} className={PRIMARY_BUTTON}>
              {t`Save`}
            </Button>
            <Button onPress={reset} isDisabled={!dirty} className={SECONDARY_BUTTON}>
              {t`Cancel`}
            </Button>
            <span role="status" className="text-small text-ink-2">
              {saved && !dirty ? t`Saved.` : null}
            </span>
          </div>
        ) : null}
        {patch.isError ? <p role="alert" className="font-bold text-bad">{errorText(patch.error)}</p> : null}
      </section>
      <aside aria-labelledby="liner-h" className={`${PANEL} flex h-fit flex-col gap-3`}>
        <h4 id="liner-h" className="font-bold">{t`Preview`}</h4>
        <div className="flex justify-center rounded-r2 bg-sunken p-3">
          <LinerPreview page={pageSizeMm(g)} strips={strips} />
        </div>
        <p className="text-small text-ink-2">
          {where ? t`Back of the liner. The code goes in the marked strip.` : t`No free strip of this print takes the code.`}
        </p>
      </aside>
    </div>
  );
}

function DefaultBadge() {
  const { t } = useLingui();
  return <span className="rounded-full bg-accent-soft px-2 py-0.5 text-small font-bold text-ink">{t`Default for this sheet`}</span>;
}
