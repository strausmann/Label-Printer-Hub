// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { plural } from "@lingui/core/macro";
import { Trans, useLingui } from "@lingui/react/macro";
import { Link } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { Button, Label, Radio, RadioGroup } from "react-aria-components";
import { printInterrupted, sheetIdJobFailed } from "../../api/errorDetail";
import { PRIMARY_BUTTON } from "../../shell/SignIn";
import { useSheetTypes } from "../archive/api";
import { useCapabilities } from "../calibration/api";
import { usePrinters } from "../printers/api";
import { HINT, LABEL, ModalDialog, SelectField } from "../settings/controls";
import { SECONDARY_BUTTON } from "../ui";
import { useCreateSheet, useMarginCheck, useNextCode, type MarginCheck, type SheetCreate, type SheetCreated } from "./api";
import type { GridCell } from "./cellState";
import { useSheetErrorText } from "./errors";
import { GeometryDiagram } from "./GeometryDiagram";
import { SheetGrid } from "./SheetGrid";
import { SheetTypeCombobox } from "./SheetTypeCombobox";

type Placement = NonNullable<SheetCreate["id_placement"]>;

const NO_TYPE = "";
const NO_PRINTER = "";

/** The band the ID goes into, in words; `null` when the server did not name one. */
function useBandWord(): (band: MarginCheck["band"]) => string {
  const { t } = useLingui();
  return (band) => {
    switch (band) {
      case "top":
        return t`top margin`;
      case "bottom":
        return t`bottom margin`;
      case "left":
        return t`left margin`;
      case "right":
        return t`right margin`;
      default:
        return t`margin`;
    }
  };
}

/** What the margin check found, as one sentence: where the ID goes, or that it cannot go anywhere. */
function MarginResult({ check, isError }: { check: MarginCheck | undefined; isError: boolean }) {
  const { t } = useLingui();
  const bandWord = useBandWord();
  let text: string | null = null;
  if (isError) text = t`The margin could not be checked on this printer.`;
  else if (check) {
    if (!check.printable) text = t`The ID will not be printed on this printer, add it by hand.`;
    else {
      const where = bandWord(check.band);
      text = check.qr ? t`The ID will be printed in the ${where}, with QR.` : t`The ID will be printed in the ${where}, text only.`;
    }
  }
  return (
    <div role="status" className="min-h-6 pl-8 text-small text-ink-2">
      {text}
    </div>
  );
}

const RADIO =
  "group flex min-h-11 cursor-pointer items-start gap-3 rounded-r2 py-2 data-[focus-visible]:outline-3 data-[focus-visible]:outline-offset-2 data-[focus-visible]:outline-link";

function PlacementOption({ value, title, description }: { value: Placement; title: string; description: string }) {
  return (
    <Radio value={value} className={RADIO}>
      <span
        aria-hidden="true"
        className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full border-2 border-line-strong bg-sunken group-data-[selected]:border-accent"
      >
        <span className="size-2.5 scale-0 rounded-full bg-accent transition-transform duration-150 ease-out group-data-[selected]:scale-100" />
      </span>
      <span className="flex min-w-0 flex-col">
        <span className="font-bold text-ink">{title}</span>
        <span className="text-small text-ink-2">{description}</span>
      </span>
    </Radio>
  );
}

function Done({
  created,
  hint,
  onClose,
  partial,
}: {
  created: SheetCreated | null;
  hint: string | null;
  onClose: () => void;
  partial: string | null;
}) {
  const { t } = useLingui();
  const code = created?.code ?? partial ?? "";
  const hinted = hint ?? "";
  return (
    <div className="flex flex-col gap-4">
      <p role="status" className="text-section font-bold">
        {created ? t`Sheet ${code} was added.` : t`Sheet ${code} was added, but its ID label could not be queued.`}
      </p>
      {created && hint && hint !== created.code ? (
        <p>{t`The number is ${code}, not ${hinted}: another sheet was added in the meantime.`}</p>
      ) : null}
      {created?.job_id ? (
        <p>
          {t`The ID label is in the print queue.`}{" "}
          <Link to="/jobs/$jobId" params={{ jobId: created.job_id }} className="inline-flex min-h-11 items-center text-link underline underline-offset-2">
            {t`Show the ID label job`}
          </Link>
        </p>
      ) : null}
      <div className="flex flex-wrap gap-3">
        <Link to="/sheets/$code" params={{ code }} className={`${PRIMARY_BUTTON} no-underline`} onClick={onClose}>
          {t`Open ${code}`}
        </Link>
        <Button onPress={onClose} className={SECONDARY_BUTTON}>
          {t`Close`}
        </Button>
      </div>
    </div>
  );
}

function AddSheetForm({ onClose }: { onClose: () => void }) {
  const { t } = useLingui();
  const errorText = useSheetErrorText();
  const create = useCreateSheet();
  const types = useSheetTypes();
  const printers = usePrinters();

  const [typeKey, setTypeKey] = useState(NO_TYPE);
  const [marked, setMarked] = useState<ReadonlySet<number>>(new Set());
  const [placement, setPlacement] = useState<Placement>("margin");
  const [printerId, setPrinterId] = useState(NO_PRINTER);
  const [trayChoice, setTrayChoice] = useState<string | null>(null);
  const [created, setCreated] = useState<{ sheet: SheetCreated; hint: string | null } | null>(null);

  const type = types.data?.find((x) => x.key === typeKey);
  const gridBox = useRef<HTMLDivElement>(null);
  // The tap view pans both ways: a new grid starts at its leading edge, so the first column is the first thing seen.
  useEffect(() => {
    const scroller = gridBox.current?.querySelector<HTMLElement>("[data-scroll]");
    if (scroller) {
      scroller.scrollLeft = 0;
      scroller.scrollTop = 0;
    }
  }, [typeKey]);
  const next = useNextCode(type ? type.key : null);
  const pagePrinters = (printers.data ?? []).filter((p) => p.backend === "ipp" && p.enabled);
  const caps = useCapabilities(printerId);
  const trays = (caps.data?.trays ?? []).filter((x) => x.enabled);
  const tray = trays.find((x) => x.key === trayChoice) ?? trays.find((x) => x.is_default) ?? trays[0];
  const trayKey = tray?.key ?? null;
  // The margin depends on the tray's calibration, so ask once the trays are known, not twice.
  // An answer is known once it came, or failed: a failure must not look like "no trays".
  const capsKnown = printerId !== NO_PRINTER && caps.isSuccess;
  const margin = useMarginCheck(type?.key ?? null, capsKnown ? printerId : null, trayKey);

  function chooseType(key: string) {
    setTypeKey(key);
    setMarked(new Set()); // another type has other cells
    create.reset();
  }
  function choosePrinter(id: string) {
    setPrinterId(id);
    setTrayChoice(null);
  }
  const toggle = (n: number) =>
    setMarked((prev) => {
      const nextSet = new Set(prev);
      if (!nextSet.delete(n)) nextSet.add(n);
      return nextSet;
    });

  const partial = sheetIdJobFailed(create.error)?.sheetCode ?? null;
  if (created || partial) {
    return <Done created={created?.sheet ?? null} hint={created?.hint ?? null} partial={partial} onClose={onClose} />;
  }

  const needsPrinter = placement === "cell";
  let blocker: string | null = null;
  if (needsPrinter) {
    if (printerId === NO_PRINTER) blocker = t`Choose a printer and a tray to print the ID label.`;
    else if (caps.isError) blocker = t`The printer could not be asked for its trays. Try again in a moment.`;
    else if (capsKnown && trayKey === null) blocker = t`This printer reports no trays, so it cannot print the ID label.`;
  }
  const ready = !!type && !create.isPending && (!needsPrinter || (printerId !== NO_PRINTER && trayKey !== null));

  function submit() {
    if (!type || !ready) return;
    const body: SheetCreate = {
      type: type.key,
      used_cells: [...marked].sort((a, b) => a - b).map((cell) => ({ cell })),
      id_placement: placement,
      ...(placement === "cell" ? { printer: printerId, tray: trayKey } : {}),
    };
    const hint = next.data?.code ?? null;
    create.mutate(body, { onSuccess: (sheet) => setCreated({ sheet, hint }) });
  }

  const cells: GridCell[] = [...marked].map((cell) => ({ cell, state: "used" }));
  const interrupted = printInterrupted(create.error);
  const hintCode = next.data?.code;

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
      className="flex min-w-0 flex-col gap-6"
    >
      <div className="flex flex-col gap-2">
        <SheetTypeCombobox
          label={t`Sheet type`}
          types={types.data ?? []}
          value={typeKey}
          noneOption={{ id: NO_TYPE, label: t`Choose a sheet type` }}
          onChange={chooseType}
        />
        {types.isError ? <p role="alert">{t`The sheet types could not be loaded.`}</p> : null}
        {type && hintCode ? (
          <p className="text-small text-ink-2">
            <Trans>
              It will probably become <span className="font-mono whitespace-nowrap">{hintCode}</span>.
            </Trans>
          </p>
        ) : null}
        {type && !type.allow_qr ? (
          <p className="text-small text-ink">{t`The labels of this type are too small for a QR code, so the ID is printed as text only.`}</p>
        ) : null}
      </div>

      {type ? (
        <>
          <section aria-labelledby="used-cells-heading" className="flex min-w-0 flex-col gap-2">
            <h3 id="used-cells-heading" className={LABEL}>
              {t`Cells already used`}
            </h3>
            <p className={HINT}>{t`Tap the labels that are already gone. A fresh sheet needs none.`}</p>
            <div ref={gridBox} className="min-w-0">
              <SheetGrid
                geometry={type.geometry}
                cells={cells}
                mode="select"
                onToggle={toggle}
                label={t`Cells already used`}
                selectable={(c) => c.state === "free" || c.state === "used"}
              />
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <p aria-live="polite" className="text-small font-bold">
                {marked.size === 0
                  ? t`Nothing marked yet`
                  : plural(marked.size, { one: "# cell marked as used", other: "# cells marked as used" })}
              </p>
              {marked.size > 0 ? (
                <Button onPress={() => setMarked(new Set())} className={`${SECONDARY_BUTTON} h-11`}>
                  {t`Clear marks`}
                </Button>
              ) : null}
            </div>
            <details className="text-small">
              <summary className="min-h-11 cursor-pointer py-2.5 text-link">{t`Measurements of this type`}</summary>
              <GeometryDiagram geometry={type.geometry} hints={type.hints} />
            </details>
          </section>

          <section aria-labelledby="printer-heading" className="flex min-w-0 flex-col gap-3">
            <h3 id="printer-heading" className={LABEL}>
              {t`Printer and tray`}
            </h3>
            <p className={HINT}>{t`Optional. It checks where the ID can go, and it is needed to print the ID label.`}</p>
            <div className="grid gap-4 sm:grid-cols-2">
              <SelectField
                label={t`Printer`}
                value={printerId}
                options={[{ id: NO_PRINTER, label: t`No printer` }, ...pagePrinters.map((p) => ({ id: p.id, label: p.name }))]}
                onChange={choosePrinter}
              />
              {printerId !== NO_PRINTER && trays.length > 0 ? (
                <div className="flex min-w-0 flex-col gap-1.5">
                  <SelectField
                    label={t`Tray`}
                    value={trayKey ?? ""}
                    options={trays.map((x) => ({ id: x.key, label: x.label }))}
                    onChange={setTrayChoice}
                  />
                  {tray?.load_hint ? <p className={HINT}>{tray.load_hint}</p> : null}
                </div>
              ) : null}
            </div>
          </section>

          <RadioGroup value={placement} onChange={(v) => setPlacement(v as Placement)} className="flex min-w-0 flex-col gap-1">
            <Label className={LABEL}>{t`Where the sheet ID goes`}</Label>
            <PlacementOption
              value="margin"
              title={t`In the margin`}
              description={t`The ID is printed in the margin of the sheet with the first print. No label is used.`}
            />
            {printerId !== NO_PRINTER ? <MarginResult check={margin.data} isError={margin.isError} /> : null}
            <PlacementOption
              value="cell"
              title={t`In the first free cell`}
              description={t`The ID takes the first free label and is printed right away.`}
            />
            <PlacementOption
              value="manual"
              title={t`By hand`}
              description={t`Nothing is printed. You write the code on the sheet yourself.`}
            />
          </RadioGroup>
        </>
      ) : null}

      {blocker ? <p className={HINT}>{blocker}</p> : null}
      {create.isError ? (
        <p role="alert" className="font-bold text-bad">
          {interrupted ? t`The ID label was queued only in part. Look at the print jobs.` : errorText(create.error, t`The sheet could not be added.`)}
        </p>
      ) : null}
      {/* The actions stay in reach while the form scrolls inside the dialog. */}
      <div className="sticky -bottom-4 -mx-4 -mb-4 flex flex-wrap gap-3 border-t border-line bg-surface px-4 pt-3 pb-4 sm:-bottom-6 sm:-mx-6 sm:-mb-6 sm:px-6 sm:pb-6">
        <Button type="submit" isDisabled={!ready} className={PRIMARY_BUTTON}>
          {placement === "cell" ? t`Add and print ID label` : t`Add sheet`}
        </Button>
        <Button onPress={onClose} className={SECONDARY_BUTTON}>
          {t`Cancel`}
        </Button>
      </div>
    </form>
  );
}

/** "+ New sheet": a sheet type, the cells that are already used, and where the sheet ID goes (spec 17.1). */
export function AddSheetDialog({ isOpen, onClose }: { isOpen: boolean; onClose: () => void }) {
  const { t } = useLingui();
  // A fresh form for every opening, while the old one stays on screen during the closing animation.
  const [opened, setOpened] = useState(0);
  const [wasOpen, setWasOpen] = useState(false);
  if (isOpen !== wasOpen) {
    setWasOpen(isOpen);
    if (isOpen) setOpened((n) => n + 1);
  }
  return (
    <ModalDialog title={t`Add a sheet`} isOpen={isOpen} onClose={onClose} wide>
      <AddSheetForm key={opened} onClose={onClose} />
    </ModalDialog>
  );
}
