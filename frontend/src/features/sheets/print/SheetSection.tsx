import { useLingui } from "@lingui/react/macro";
import { useMemo, useState } from "react";
import { Button, Radio, RadioGroup } from "react-aria-components";
import { cellsTaken, insufficientCells, planChanged, printInterrupted } from "../../../api/errorDetail";
import { PRIMARY_BUTTON } from "../../../shell/SignIn";
import { useSheetTypes, type SheetTypeRead } from "../../archive/api";
import type { CartItem } from "../../lookup/cart";
import { usePrinterStatus, type Printer } from "../../printers/api";
import { describePrinter } from "../../printers/model";
import { ReasonLine } from "../../printers/PageStatus";
import { HINT, LABEL, SelectField } from "../../settings/controls";
import { PANEL, SECTION_HEADING } from "../../ui";
import { useNextCode, usePrintSheets, useSheet, useSheetPreview, useSheets, type SheetPrintRequest, type SheetPrintResponse } from "../api";
import { formatMm, type GridCell } from "../cellState";
import { SheetGrid } from "../SheetGrid";
import { typeLabelWithKey } from "../typeLabel";
import { CapacityAlert } from "./CapacityAlert";
import { usePrintDialogErrorText } from "./errors";
import { lastType } from "./lastType";
import {
  countItems,
  expandItems,
  fittingFirst,
  freeOf,
  judgeSheet,
  MAX_ITEMS,
  placementFor,
  type Fill,
  type PlacementIn,
  type Target,
} from "./plan";
import { PartialResult, PrintResult } from "./PrintResult";
import { PrinterRow, printerWaits } from "./PrinterRow";
import { SheetPicker } from "./SheetPicker";
import { SheetPreview, ZoomToggle } from "./SheetPreview";
import { useDebounced } from "./useDebounced";

export interface SheetSectionProps {
  /** The cart lines (or the one item of an item view); every copy becomes a label. */
  items: readonly CartItem[];
  printer: Printer;
  /** A sheet code from `/cart?sheet=<code>`. */
  preselectedSheet?: string | undefined;
  /** Called once the hub accepted the print (202): the cart empties then, not before. */
  onAccepted?: () => void;
}

/** A worst-case preview takes seconds to render on the server, so it is asked for only once the choices have settled. */
const PREVIEW_DEBOUNCE_MS = 400;

/** Stands in for the request while there is none: the query is off then and never sends it. */
const NO_REQUEST: SheetPrintRequest = { items: [], placements: [] };

const typeOption = (type: SheetTypeRead, locale: string) =>
  `${typeLabelWithKey(type)} · ${formatMm(type.geometry.label_w, locale).replace(/ mm$/, "")} × ${formatMm(type.geometry.label_h, locale)}`;

type PrintedPages = SheetPrintResponse["pages"];
type Changed = { kind: "plan"; sheets: string[] } | { kind: "cells"; sheet: string };

/**
 * The sheet branch of the print dialog (a page printer): which sheet, which cells, what the page
 * will look like, and the print. The preview is the server's: the print sends back what the preview
 * promised (`expected_cells`), and a changed plan is shown again and confirmed again.
 */
export function SheetSection({ items, printer, preselectedSheet, onAccepted }: SheetSectionProps) {
  const { t, i18n } = useLingui();
  const status = usePrinterStatus(printer.id);
  const types = useSheetTypes();
  const linked = useSheet(preselectedSheet ?? "");
  const print = usePrintSheets(printer.id);

  const needed = countItems(items);
  const tooMany = needed > MAX_ITEMS;
  const typeList = types.data ?? [];

  // --- the choices; a null choice means "the default derived below" ---
  const [typeChoice, setTypeChoice] = useState<string | null>(null);
  const [targetChoice, setTargetChoice] = useState<Target | null>(null);
  const [trayChoice, setTrayChoice] = useState<string | null>(null);
  const [fillMode, setFillMode] = useState<Fill["mode"]>("first_free");
  const [chosen, setChosen] = useState<readonly number[]>([]);
  const [skipped, setSkipped] = useState<readonly number[]>([]);
  const [override, setOverride] = useState<{ key: string; placements: PlacementIn[] } | null>(null);
  const [zoom, setZoom] = useState<1 | 2>(1);
  const [changed, setChanged] = useState<Changed | null>(null);
  const [result, setResult] = useState<PrintedPages | null>(null);

  // --- the sheet of the link, if any ---
  const linkedSheet = linked.data;
  const linkedVerdict = linkedSheet ? judgeSheet(linkedSheet, linkedSheet.type_key) : null;
  const linkedUsable = linkedSheet && linkedVerdict?.kind === "ok" ? linkedSheet : null;
  const linkNote = !preselectedSheet
    ? null
    : linked.isError
      ? t`The hub does not know a sheet ${preselectedSheet}.`
      : linkedVerdict?.kind === "discarded"
        ? t`${preselectedSheet} is discarded and cannot take labels any more.`
        : linkedVerdict?.kind === "full"
          ? t`${preselectedSheet} has no free cell left.`
          : null;

  // --- type ---
  const remembered = lastType.get(printer.id);
  const rememberedType = typeList.find((x) => x.key === remembered)?.key ?? null;
  const typeKey = typeChoice ?? linkedUsable?.type_key ?? rememberedType ?? typeList[0]?.key ?? null;
  const type = typeList.find((x) => x.key === typeKey) ?? null;
  const typeName = type ? typeLabelWithKey(type) : (typeKey ?? "");

  // --- sheets of the type ---
  const sheetsQuery = useSheets({ ...(typeKey ? { type: typeKey } : {}), state: "active" }, !!typeKey);
  const usable = useMemo(
    () => (sheetsQuery.data ?? []).filter((s) => s.type_key === typeKey && s.state === "active" && freeOf(s) > 0),
    [sheetsQuery.data, typeKey],
  );
  const nextCode = useNextCode(typeKey);
  const ranked = fittingFirst(usable, needed);
  const linkedHere = linkedUsable && linkedUsable.type_key === typeKey ? linkedUsable.code : null;
  const defaultTarget: Target | null = !typeKey
    ? null
    : linkedHere
      ? { kind: "sheet", code: linkedHere }
      : ranked[0]?.fits
        ? { kind: "sheet", code: ranked[0].sheet.code }
        : sheetsQuery.isPending
          ? null
          : { kind: "new" };
  const target = targetChoice ?? defaultTarget;
  const sheetCode = target?.kind === "sheet" ? target.code : null;

  // --- tray ---
  const trays = (status.data?.trays ?? []).filter((x) => x.enabled);
  const tray = trays.find((x) => x.key === trayChoice) ?? trays.find((x) => x.is_default) ?? trays[0] ?? null;

  // --- the request ---
  const fill: Fill = { mode: sheetCode ? fillMode : "first_free", chosen, skipped };
  const chosenReady = fill.mode !== "choose" || chosen.length === needed;
  const planKey = JSON.stringify([target, typeKey, fill, needed]);
  const activeOverride = override && override.key === planKey ? override : null;
  const request: SheetPrintRequest | null =
    !target || !typeKey || needed === 0 || tooMany || !chosenReady
      ? null
      : {
          items: expandItems(items),
          placements: activeOverride?.placements ?? [placementFor(target, typeKey, fill)],
          ...(tray ? { tray: tray.key } : {}),
        };
  const settled = useDebounced(request, PREVIEW_DEBOUNCE_MS);
  const preview = useSheetPreview(printer.id, settled.value ?? NO_REQUEST, settled.value !== null);
  // What the print may rely on is only a preview of the very request that is current; what is shown may be the one before it, dimmed.
  const previewData = settled.value && !preview.isPlaceholderData ? preview.data : undefined;
  const shownData = settled.value ? preview.data : undefined;

  // --- words ---
  const lineOf = (index: number): CartItem | undefined => {
    let rest = index;
    for (const line of items) {
      if (rest < line.copies) return line;
      rest -= line.copies;
    }
    return undefined;
  };
  const itemName = (index: number) => lineOf(index)?.name ?? t`An item`;
  const errorText = usePrintDialogErrorText(itemName);
  const view = describePrinter(printer, status.data, false);
  const waits = printerWaits(view.kind);
  const trayLabel = tray?.label ?? "";
  const trayText = t`Tray: ${trayLabel}`;

  // --- reactions ---
  const forget = () => {
    setChanged(null);
    setOverride(null);
    // An error or a partial result belongs to the choices that were made; the result of a finished print stays.
    print.reset();
  };
  const chooseType = (key: string) => {
    lastType.set(printer.id, key);
    setTypeChoice(key);
    setTargetChoice(null);
    setChosen([]);
    setSkipped([]);
    forget();
  };
  const chooseTarget = (next: Target) => {
    setTargetChoice(next);
    setChosen([]);
    setSkipped([]);
    forget();
  };
  const toggle = (list: readonly number[], cell: number, limit = Infinity) =>
    list.includes(cell) ? list.filter((n) => n !== cell) : list.length < limit ? [...list, cell].sort((a, b) => a - b) : list;

  const insufficient = insufficientCells(preview.error);
  const otherSheets = usable.filter((s) => s.code !== sheetCode);

  function submit() {
    if (!settled.value || !previewData) return;
    const sent = settled.value;
    setResult(null);
    print.mutate(
      { ...sent, expected_cells: previewData.expected_cells },
      {
        onSuccess: (response) => {
          setChanged(null);
          setResult(response.pages);
          onAccepted?.();
        },
        onError: (error) => {
          // The plan moved under us: the preview is asked again (the print invalidates it) and the next press is the second confirmation.
          const plan = planChanged(error);
          if (plan) setChanged({ kind: "plan", sheets: [...new Set(plan.plan.map((p) => p.sheet))] });
          else if (cellsTaken(error)) setChanged({ kind: "cells", sheet: sheetCode ?? "" });
        },
      },
    );
  }

  const printError = print.error;
  const interrupted = printInterrupted(printError);
  const changedSheet = changed?.kind === "cells" ? changed.sheet : "";
  const changedSheets = changed?.kind === "plan" ? changed.sheets.map((c) => (c === "new" ? t`a new sheet` : c)).join(", ") : "";
  const changeNote = !changed
    ? null
    : changed.kind === "cells"
      ? changedSheet
        ? t`Another computer used cells on ${changedSheet} while you were looking. Check the new plan, then confirm.`
        : t`Another computer used some of the cells while you were looking. Check the new plan, then confirm.`
      : t`Another computer changed ${changedSheets} while you were looking. Check the new plan, then confirm.`;
  const showPrintError = print.isError && !interrupted && !changed;
  const busy = print.isPending || preview.isFetching || settled.pending || preview.isPlaceholderData;
  const canPrint = !!previewData && !preview.isError && !busy && !tooMany && needed > 0;
  const buttonText = changed ? t`Print with the new plan` : waits ? t`Add to print queue` : t`Print onto sheet`;

  const idleNote = needed === 0 && !result ? t`There is nothing to print yet.` : null;

  return (
    <section aria-labelledby="sheet-section-h" className={`${PANEL} flex min-w-0 flex-col gap-5`}>
      <h2 id="sheet-section-h" className={SECTION_HEADING}>{t`Print onto a sheet`}</h2>

      <PrinterRow printer={printer} status={status.data} />
      {waits && (
        <div role="alert" className="flex flex-col gap-1 rounded-r2 border border-warn bg-sunken p-3">
          <span>{t`The printer is not ready. The pages go into the print queue and print when it is ready again.`}</span>
          <ReasonLine reasons={view.reasons} />
        </div>
      )}

      {needed > 0 && (
        <>
          <div className="grid gap-4 sm:grid-cols-2">
            <SelectField
              label={t`Sheet type`}
              value={typeKey ?? ""}
              options={typeList.map((x) => ({ id: x.key, label: typeOption(x, i18n.locale) }))}
              onChange={chooseType}
            />
            {tray && trays.length > 1 ? (
              <SelectField label={t`Tray`} value={tray.key} options={trays.map((x) => ({ id: x.key, label: x.label }))} onChange={setTrayChoice} />
            ) : tray ? (
              <p className={`${HINT} self-end`}>{trayText}</p>
            ) : (
              <p className={`${HINT} self-end`}>{t`The printer chooses the tray itself.`}</p>
            )}
          </div>

          {typeKey && !tooMany && (
            <SheetPicker
              typeKey={typeKey}
              typeLabel={typeName}
              sheets={usable}
              needed={needed}
              value={target}
              onChange={chooseTarget}
              newCode={nextCode.data?.code ?? null}
            />
          )}
          {linkNote && <p role="alert" className="text-small font-bold">{linkNote}</p>}

          {sheetCode && !tooMany && (
            <RadioGroup
              value={fillMode}
              onChange={(v) => {
                setFillMode(v as Fill["mode"]);
                forget();
              }}
              className="flex flex-col gap-1"
            >
              <span className={LABEL}>{t`Cells`}</span>
              <div className="flex flex-wrap gap-x-5">
                <FillOption value="first_free" label={t`First free cells`} />
                <FillOption value="choose" label={t`Choose cells`} />
              </div>
            </RadioGroup>
          )}

          {sheetCode && fillMode === "choose" && !tooMany && (
            <ChooseCells code={sheetCode} chosen={chosen} needed={needed} onToggle={(cell) => setChosen((c) => toggle(c, cell, needed))} />
          )}
        </>
      )}

      {idleNote && <p className="text-ink-2">{idleNote}</p>}
      {tooMany && (
        <p role="alert" className="font-bold">
          {t`${needed} labels are too many for one sheet print: at most ${MAX_ITEMS} fit in one go. Remove some, or print in two rounds.`}
        </p>
      )}

      {request && (
        <section aria-labelledby="sheet-preview-h" className="flex min-w-0 flex-col gap-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 id="sheet-preview-h" className="font-bold">{t`Preview`}</h3>
            {shownData && <ZoomToggle zoom={zoom} onChange={setZoom} />}
          </div>
          {insufficient && target && typeKey ? (
            <CapacityAlert
              needed={needed}
              freeCells={insufficient.freeCells}
              target={target}
              typeKey={typeKey}
              fill={fill}
              others={otherSheets}
              onChoose={(choice) => {
                // A sheet with room replaces the target; a split is the placements of the next preview.
                if (choice.target) chooseTarget(choice.target);
                else setOverride({ key: planKey, placements: choice.placements });
              }}
            />
          ) : preview.isError ? (
            <p role="alert" className="[overflow-wrap:anywhere]">{errorText(preview.error)}</p>
          ) : null}
          {busy && !preview.isError && (
            <p role="status" className="text-ink-2">{shownData ? t`Updating the preview…` : t`Drawing the sheet…`}</p>
          )}
          {shownData && !insufficient && (
            <div aria-busy={busy} className={busy ? "opacity-60 transition-opacity duration-150" : "transition-opacity duration-150"}>
              <SheetPreview
                data={shownData}
                itemName={itemName}
                zoom={zoom}
                skipped={skipped}
                onToggleSkip={sheetCode && fillMode === "first_free" && !activeOverride ? (cell) => { setSkipped((s) => toggle(s, cell)); forget(); } : undefined}
              />
            </div>
          )}
        </section>
      )}

      {changeNote && <p role="alert" className="font-bold [overflow-wrap:anywhere]">{changeNote}</p>}
      {interrupted && <PartialResult jobIds={interrupted.jobIds} />}
      {showPrintError && <p role="alert" className="[overflow-wrap:anywhere]">{errorText(printError)}</p>}
      {result && <PrintResult pages={result} />}

      {needed > 0 && (
        <div>
          <Button className={`${PRIMARY_BUTTON} max-sm:w-full`} isDisabled={!canPrint} onPress={submit}>
            {buttonText}
          </Button>
        </div>
      )}
    </section>
  );
}

const RADIO =
  "group flex min-h-11 cursor-pointer items-center gap-2 rounded-r2 data-[focus-visible]:outline-3 data-[focus-visible]:outline-offset-2 data-[focus-visible]:outline-link";

/** A radio with a visible ring and dot: the choice is never only a label. */
function FillOption({ value, label }: { value: Fill["mode"]; label: string }) {
  return (
    <Radio value={value} className={RADIO}>
      <span
        aria-hidden="true"
        className="flex size-5 shrink-0 items-center justify-center rounded-full border-2 border-line-strong bg-sunken group-data-[selected]:border-accent"
      >
        <span className="size-2.5 scale-0 rounded-full bg-accent transition-transform duration-150 ease-out group-data-[selected]:scale-100" />
      </span>
      {label}
    </Radio>
  );
}

/** The sheet's own cells to pick from: free ones can be chosen, the ones chosen read as new. */
function ChooseCells({ code, chosen, needed, onToggle }: { code: string; chosen: readonly number[]; needed: number; onToggle: (cell: number) => void }) {
  const { t } = useLingui();
  const sheet = useSheet(code);
  const cells: GridCell[] = useMemo(() => {
    const own = (sheet.data?.cells ?? []).map((c) => ({ cell: c.cell, state: c.state, ...(c.purpose ? { purpose: c.purpose } : {}) }));
    return [...own, ...chosen.map((cell) => ({ cell, state: "new" as const }))];
  }, [sheet.data, chosen]);
  if (!sheet.data) return <p role="status" className="text-ink-2">{t`Loading…`}</p>;
  const count = chosen.length;
  return (
    <div className="flex min-w-0 flex-col gap-2">
      <p className="font-bold tabular-nums">{t`${count} of ${needed} cells chosen`}</p>
      <SheetGrid
        geometry={sheet.data.geometry}
        cells={cells}
        mode="select"
        label={code}
        onToggle={onToggle}
        selectable={(c) => c.state === "free" || c.state === "new"}
      />
    </div>
  );
}
