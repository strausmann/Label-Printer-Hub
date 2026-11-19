// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useLingui } from "@lingui/react/macro";
import { useState } from "react";
import { Button } from "react-aria-components";
import { useSheetType } from "../archive/api";
import { Badge } from "../archive/fields";
import { useCapabilities } from "../calibration/api";
import { usePrinters } from "../printers/api";
import { HINT, ModalDialog, SelectField } from "../settings/controls";
import { PANEL, PRIMARY_BUTTON, SECONDARY_BUTTON, SECTION_HEADING } from "../ui";
import { useConfirmBackSide, usePrintMarginId, type SheetRead } from "./api";
import { useSheetErrorText } from "./errors";
import { BackSideDialog } from "./backSide/BackSideDialog";

/** Whether the sheet's code is due on the back and not confirmed yet: a `back_side` sheet, or an extra code on the back still pending. */
const backPending = (sheet: SheetRead) => sheet.back_side_missing;

/** Whether the panel shows the back-side line: a code on the back exists or is asked for. A sheet that never asked for one shows none. */
const hasBackSide = (sheet: SheetRead) => sheet.id_placement === "back_side" || sheet.back_side_state !== null;

/**
 * "Reprint margin code": the printer and tray of a page that prints only the code in the margin of a printed margin sheet.
 * The same choice as the back-side activation (enabled page printers, the tray's default first).
 */
function MarginReprintDialog({ code, onClose }: { code: string; onClose: () => void }) {
  const { t } = useLingui();
  const errorText = useSheetErrorText();
  const printers = usePrinters();
  const pagePrinters = (printers.data ?? []).filter((p) => p.backend === "ipp" && p.enabled);
  const [printerId, setPrinterId] = useState("");
  const effectivePrinter = printerId || pagePrinters[0]?.id || "";
  const caps = useCapabilities(effectivePrinter);
  const trays = (caps.data?.trays ?? []).filter((x) => x.enabled);
  const [trayChoice, setTrayChoice] = useState<string | null>(null);
  const tray = trays.find((x) => x.key === trayChoice) ?? trays.find((x) => x.is_default) ?? trays[0];
  const print = usePrintMarginId();

  function submit() {
    if (!effectivePrinter) return;
    print.mutate({ code, body: { printer: effectivePrinter, tray: tray?.key ?? null } }, { onSuccess: onClose });
  }

  return (
    <ModalDialog title={t`Reprint margin code`} isOpen onClose={onClose}>
      <p className="max-w-prose">{t`Put the sheet back in the printer the way it went in the first time. Only the code in the margin is printed, no label.`}</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <SelectField
          label={t`Printer`}
          value={effectivePrinter}
          options={pagePrinters.map((p) => ({ id: p.id, label: p.name }))}
          onChange={(id) => {
            setPrinterId(id);
            setTrayChoice(null);
          }}
        />
        {trays.length > 0 ? <SelectField label={t`Tray`} value={tray?.key ?? ""} options={trays.map((x) => ({ id: x.key, label: x.label }))} onChange={setTrayChoice} /> : null}
      </div>
      {pagePrinters.length === 0 && printers.isSuccess ? <p className={HINT}>{t`No page printer is set up.`}</p> : null}
      {print.isError ? (
        <p role="alert" className="font-bold text-bad">
          {errorText(print.error, t`The margin code could not be printed.`)}
        </p>
      ) : null}
      <div className="flex flex-wrap gap-3">
        <Button onPress={submit} isDisabled={!effectivePrinter || print.isPending} className={PRIMARY_BUTTON}>
          {t`Print margin code`}
        </Button>
        <Button onPress={onClose} className={SECONDARY_BUTTON}>
          {t`Cancel`}
        </Button>
      </div>
    </ModalDialog>
  );
}

/**
 * The sheet code of one sheet (1.7.0, mockup approved on rc.7): where it is, whether it is printed, the code on the back
 * if one exists or is wanted, and what can be printed again. Shown for every sheet; the buttons only for a key that may
 * print and a sheet that is not discarded.
 */
export function SheetCodePanel({ sheet, canWrite }: { sheet: SheetRead; canWrite: boolean }) {
  const { t } = useLingui();
  const errorText = useSheetErrorText();
  const confirm = useConfirmBackSide();
  const [dialog, setDialog] = useState<"back" | "margin" | null>(null);
  const discarded = sheet.state === "discarded";
  const canEdit = canWrite && !discarded;
  const placement = sheet.id_placement;

  // R-350-11: an unprinted margin sheet switches to the back only when its type puts the code there. A manual
  // sheet's code was stuck on by hand: like a printed one, it gets an extra code on the back and keeps its place.
  const switchable = canEdit && !sheet.id_printed && placement === "margin";
  const sheetType = useSheetType(sheet.type_key, switchable);
  const offerBack =
    canEdit &&
    (placement === "back_side" ||
      placement === "manual" ||
      sheet.id_printed ||
      (switchable && sheetType.data?.id_placement_resolved === "back_side"));
  const offerMargin = canEdit && placement === "margin" && sheet.id_printed;

  const placementWord = {
    cell: t({ message: "In a cell", context: "sheet code placement" }),
    margin: t({ message: "In the margin", context: "sheet code placement" }),
    manual: t({ message: "Added by hand", context: "sheet code placement" }),
    back_side: t({ message: "On the back of the liner", context: "sheet code placement" }),
  }[placement];
  const stateWord =
    placement === "manual"
      ? null
      : placement === "back_side"
        ? sheet.id_printed
          ? t`printed`
          : t({ message: "not confirmed", context: "sheet code" })
        : sheet.id_printed
          ? t`printed`
          : t`not printed yet`;
  const waitsForCells = !discarded && !sheet.id_printed && (placement === "cell" || placement === "margin") && sheet.unconfirmed > 0;

  return (
    <section aria-labelledby="sheet-code-heading" className={`${PANEL} flex flex-col gap-3`}>
      <h2 id="sheet-code-heading" className={SECTION_HEADING}>
        {t`Sheet code`}
      </h2>
      <div className="flex flex-col gap-1.5 text-small">
        <p className="flex min-w-0 items-center gap-2 font-mono text-body font-bold [overflow-wrap:anywhere]">
          <svg viewBox="0 0 12 12" width="12" height="12" aria-hidden="true" className="shrink-0 fill-ink">
            <path d="M0 0h5v5H0zM7 0h5v5H7zM0 7h5v5H0zM7 7h2v2H7zM10 10h2v2h-2zM10 7h2v2h-2zM7 10h2v2H7z" />
          </svg>
          {sheet.code}
        </p>
        <p data-testid="sheet-code-state">{stateWord ? `${placementWord} · ${stateWord}` : placementWord}</p>
        {waitsForCells ? <p className="text-ink-2">{t`Resolve the unconfirmed cells first; the sheet code waits for them`}</p> : null}
        {hasBackSide(sheet) ? (
          <p className="flex flex-wrap items-center gap-2" data-testid="sheet-code-back">
            <span>{t`Back side:`}</span>
            {backPending(sheet) ? (
              <Badge tone="warn">{t({ message: "missing", context: "back side" })}</Badge>
            ) : (
              <span className="font-bold">{t({ message: "confirmed", context: "back side" })}</span>
            )}
          </p>
        ) : null}
      </div>

      {canEdit && (offerMargin || offerBack) ? (
        <div className="flex flex-col gap-2">
          {offerMargin ? (
            <Button onPress={() => setDialog("margin")} className={SECONDARY_BUTTON}>
              {t`Reprint margin code`}
            </Button>
          ) : null}
          {offerBack ? (
            <Button onPress={() => setDialog("back")} className={SECONDARY_BUTTON}>
              {t`Print back side`}
            </Button>
          ) : null}
          {backPending(sheet) ? (
            <Button onPress={() => confirm.mutate(sheet.code)} isDisabled={confirm.isPending} className={SECONDARY_BUTTON}>
              {t`Yes, the back side is printed`}
            </Button>
          ) : null}
        </div>
      ) : null}
      {confirm.isError ? (
        <p role="alert" className="font-bold text-bad">
          {errorText(confirm.error)}
        </p>
      ) : null}

      {dialog === "back" ? <BackSideDialog code={sheet.code} isOpen onClose={() => setDialog(null)} title={t`Print back side`} /> : null}
      {dialog === "margin" ? <MarginReprintDialog code={sheet.code} onClose={() => setDialog(null)} /> : null}
    </section>
  );
}
