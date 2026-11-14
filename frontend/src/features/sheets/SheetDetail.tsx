import { plural } from "@lingui/core/macro";
import { useLingui } from "@lingui/react/macro";
import { useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "@tanstack/react-router";
import { useMemo, useRef, useState, type ReactNode } from "react";
import { Button } from "react-aria-components";
import { ApiError } from "../../api/client";
import { useSession } from "../../app/session";
import { PRIMARY_BUTTON } from "../../shell/SignIn";
import { Badge } from "../archive/fields";
import { isLookupApp, useAppName } from "../lookup/apps";
import { ModalDialog, TextInput } from "../settings/controls";
import { PANEL, SECONDARY_BUTTON, SECTION_HEADING } from "../ui";
import { useMarkCells, useResolveAllCells, useResolveCells, useSheet, useUnmarkCells, type SheetRead } from "./api";
import { cellStateWord, formatMm, type GridCell, type Translate } from "./cellState";
import { useSheetErrorText } from "./errors";
import { sheetKey } from "./keys";
import { SheetGrid, SheetLegend } from "./SheetGrid";
import { DiscardDialog, Usage } from "./SheetsPage";

/** The server's limit for the purpose of one cell (`MarkedCellIn.purpose`). */
const MAX_PURPOSE = 120;
/** More cells than this and the list starts folded: a 189-cell sheet would otherwise be a screen-high wall of text. */
const LONG_LIST = 30;

type CellData = SheetRead["cells"][number];
type Mode = "view" | "mark" | "unmark";

/** The words for who wrote a cell: an integration by its name, a hand mark, any other client as sent. The ID label is told by `is_id_cell`, not by this. */
function useSourceName(): (source: string) => string {
  const { t } = useLingui();
  const appName = useAppName();
  return (source) => {
    if (isLookupApp(source)) return appName(source);
    if (source === "manual") return t({ message: "marked by hand", context: "cell source" });
    return source;
  };
}

/** "Cell 5 → flour · Grocy": what one cell holds. The same line is read on focus and listed below the grid. */
function useCellLine(): (cell: CellData) => string {
  const { t } = useLingui();
  const sourceName = useSourceName();
  return (cell) => {
    const n = cell.cell;
    const purpose = cell.purpose && cell.purpose.trim() !== "" ? cell.purpose : t`no purpose`;
    const source = cell.is_id_cell ? t({ message: "Sheet ID", context: "cell source" }) : sourceName(cell.source);
    return t`Cell ${n} → ${purpose} · ${source}`;
  };
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-wrap gap-x-2">
      <dt className="font-bold">
        {label}
        <span className="sr-only">: </span>
      </dt>
      <dd className="min-w-0 [overflow-wrap:anywhere]">{children}</dd>
    </div>
  );
}

/** The time as visible text: nothing here is readable only on hover. */
function Time({ iso, withTime }: { iso: string; withTime?: boolean }) {
  const { i18n } = useLingui();
  const date = new Date(iso);
  return (
    <time dateTime={iso}>
      {withTime ? date.toLocaleString(i18n.locale, { dateStyle: "medium", timeStyle: "short" }) : date.toLocaleDateString(i18n.locale, { dateStyle: "medium" })}
    </time>
  );
}

/** The ID cell is the one the hub flags (`is_id_cell`); it is never inferred from `source`, which any hub-written cell has. */
function toGridCell(c: CellData): GridCell {
  return { cell: c.cell, state: c.state, purpose: c.purpose ?? undefined, isId: c.is_id_cell };
}

function SheetBody({ sheet, canWrite }: { sheet: SheetRead; canWrite: boolean }) {
  const { t, i18n } = useLingui();
  const translate: Translate = (d) => i18n._(d);
  const errorText = useSheetErrorText();
  const cellLine = useCellLine();
  const client = useQueryClient();
  const code = sheet.code;
  const mark = useMarkCells();
  const unmark = useUnmarkCells();
  const resolve = useResolveCells();
  const resolveAll = useResolveAllCells();
  // The count is frozen when the question opens: it is the number the person read, and the one the server checks.
  const [resolvingAll, setResolvingAll] = useState<{ outcome: "printed" | "not_printed"; count: number } | null>(null);
  const [chosenMode, setChosenMode] = useState<Mode>("view");
  const [picked, setPicked] = useState<ReadonlySet<number>>(new Set());
  const [purpose, setPurpose] = useState("");
  const [inspected, setInspected] = useState<number | null>(null);
  const [discarding, setDiscarding] = useState(false);
  const unconfirmedHeading = useRef<HTMLHeadingElement>(null);

  const discarded = sheet.state === "discarded";
  const byNumber = useMemo(() => new Map(sheet.cells.map((c) => [c.cell, c])), [sheet.cells]);
  const handMarked = useMemo(() => new Set(sheet.cells.filter((c) => c.marked_by_hand).map((c) => c.cell)), [sheet.cells]);
  const unconfirmed = sheet.cells.filter((c) => c.state === "unconfirmed");
  const canEdit = canWrite && !discarded;
  // The sheet can be discarded, or taken away from this key, while a choice is open: then it is only viewed.
  const mode: Mode = canEdit ? chosenMode : "view";

  // A live change can take a chosen cell away (reserved by a job, un-marked elsewhere): it drops out of the choice.
  const chosen = useMemo(
    () => [...picked].filter((n) => (mode === "mark" ? !byNumber.has(n) : mode === "unmark" ? handMarked.has(n) : false)).sort((a, b) => a - b),
    [picked, mode, byNumber, handMarked],
  );

  const gridCells: GridCell[] = useMemo(() => {
    const cells = sheet.cells.filter((c) => !(mode === "unmark" && chosen.includes(c.cell))).map(toGridCell);
    // What the choice will be: chosen cells to mark show as used, chosen cells to un-mark as free.
    if (mode === "mark") for (const cell of chosen) cells.push({ cell, state: "used" });
    return cells;
  }, [sheet.cells, mode, chosen]);

  const selectable = (c: GridCell) => (mode === "mark" ? !byNumber.has(c.cell) : mode === "unmark" ? handMarked.has(c.cell) : false);

  function enter(next: Mode) {
    mark.reset();
    unmark.reset();
    setPicked(new Set());
    setPurpose("");
    setChosenMode(next);
  }
  const leave = () => enter("view");

  function toggle(cell: number) {
    setPicked((current) => {
      const next = new Set(current);
      if (!next.delete(cell)) next.add(cell);
      return next;
    });
  }

  /** A refused write often means the sheet changed under us: show its current state. */
  const reload = () => void client.invalidateQueries({ queryKey: sheetKey(code) });

  function askResolveAll(outcome: "printed" | "not_printed") {
    resolveAll.reset();
    setResolvingAll({ outcome, count: unconfirmed.length });
  }
  function confirmResolveAll() {
    if (!resolvingAll) return;
    const { outcome, count } = resolvingAll;
    resolveAll.mutate(
      { code, outcome, expectedCount: count },
      {
        onSuccess: () => setResolvingAll(null),
        onError: () => {
          setResolvingAll(null);
          reload();
        },
      },
    );
  }

  function submitMark() {
    const text = purpose.trim();
    mark.mutate({ code, cells: chosen.map((cell) => (text ? { cell, purpose: text } : { cell })) }, { onSuccess: leave, onError: reload });
  }
  function submitUnmark() {
    unmark.mutate({ code, cells: chosen }, { onSuccess: leave, onError: reload });
  }

  const idNotPrinted = !discarded && sheet.id_placement !== "manual" && !sheet.id_printed;
  const sizeLine = `${formatMm(sheet.label_w, i18n.locale).replace(/ mm$/, "")} × ${formatMm(sheet.label_h, i18n.locale)}`;
  const placementWord = { cell: t`in a cell`, margin: t`in the margin`, manual: t`added by hand` }[sheet.id_placement];
  const writing = mode === "mark" ? mark : unmark;
  const inspectedCell = inspected === null ? null : byNumber.get(inspected);
  // What the grid draws wins: a cell chosen to mark shows as used, one chosen to un-mark as free.
  const isChosen = inspected !== null && chosen.includes(inspected);
  const cellList = (
    <ul aria-label={t`Cells in use`} className="m-0 flex list-none flex-col gap-1.5 rounded-r2 border border-line p-3 text-small">
      {sheet.cells.map((c) => (
        <li key={c.cell} className="[overflow-wrap:anywhere]">
          {cellLine(c)}
          {c.state !== "used" ? <span className="ml-2 font-bold">{cellStateWord(c.state, translate)}</span> : null}
        </li>
      ))}
    </ul>
  );
  const discardedOn = sheet.discarded_at ? new Date(sheet.discarded_at).toLocaleDateString(i18n.locale, { dateStyle: "medium" }) : "";

  return (
    <div className="flex min-w-0 flex-col gap-6">
      <div className="flex min-w-0 flex-col gap-1.5">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="min-w-0 font-mono text-title font-bold [overflow-wrap:anywhere]">{code}</h1>
          {discarded ? <Badge tone="warn">{t({ message: "discarded", context: "sheet state" })}</Badge> : null}
        </div>
        <p className="text-ink-2 [overflow-wrap:anywhere]">
          {sheet.type_label} · {sizeLine}
        </p>
        {discarded && sheet.discarded_at ? (
          <p className="font-bold">{t`Discarded on ${discardedOn}, this ID is not used again.`}</p>
        ) : null}
        {idNotPrinted ? (
          <div className="flex flex-col gap-0.5">
            <p className="font-bold">{t`Sheet ID not printed yet`}</p>
            {sheet.unconfirmed > 0 ? <p className="text-ink-2">{t`Resolve the unconfirmed cells first; the sheet ID waits for them`}</p> : null}
          </div>
        ) : null}
      </div>

      <div className="grid min-w-0 gap-6 lg:grid-cols-[minmax(0,1fr)_21rem] lg:items-start">
        <aside className="flex min-w-0 flex-col gap-4 lg:col-start-2 lg:row-start-1">
          <section aria-labelledby="facts-heading" className={`${PANEL} flex flex-col gap-3`}>
            <h2 id="facts-heading" className={SECTION_HEADING}>
              {t`This sheet`}
            </h2>
            <Usage sheet={sheet} />
            <dl className="m-0 flex flex-col gap-1.5 text-small">
              <Fact label={t`Sheet ID`}>
                {sheet.id_printed ? t`printed` : t`not printed yet`}, {placementWord}
              </Fact>
              <Fact label={t`Feed mark printed`}>{sheet.feed_mark_printed ? t`yes` : t`no`}</Fact>
              <Fact label={t`Last used`}>{sheet.last_used_at ? <Time iso={sheet.last_used_at} withTime /> : t`Not used yet`}</Fact>
              <Fact label={t`Sheet type`}>
                {sheet.type_label} (v{sheet.version})
              </Fact>
              {sheet.note ? <Fact label={t`Note`}>{sheet.note}</Fact> : null}
            </dl>
          </section>

          {canEdit && mode === "view" ? (
            <section aria-label={t`Actions`} className="flex flex-wrap items-center gap-3">
              {sheet.free > 0 ? (
                <Button onPress={() => enter("mark")} className={SECONDARY_BUTTON}>
                  {t`Mark cells as used`}
                </Button>
              ) : null}
              {handMarked.size > 0 ? (
                <Button onPress={() => enter("unmark")} className={SECONDARY_BUTTON}>
                  {t`Un-mark cells`}
                </Button>
              ) : null}
              {sheet.free > 0 ? (
                <Link to="/cart" search={{ sheet: code }} className={`${PRIMARY_BUTTON} no-underline`}>
                  {t`Print onto this sheet`}
                </Link>
              ) : null}
              {sheet.reserved > 0 ? (
                <span className="text-small text-ink-2">{t`In use by a running job`}</span>
              ) : (
                <Button onPress={() => setDiscarding(true)} className={SECONDARY_BUTTON}>
                  {t`Discard sheet`}
                </Button>
              )}
            </section>
          ) : null}

          {/* Outside the section: when the last unconfirmed cell is settled elsewhere the section goes, the words stay. */}
          {canEdit && resolveAll.isError ? (
            <p role="alert" className="font-bold text-bad">
              {errorText(resolveAll.error, t`The cells could not be resolved.`)}
            </p>
          ) : null}

          {canEdit && unconfirmed.length > 0 ? (
            <section aria-labelledby="unconfirmed-heading" className={`${PANEL} flex flex-col gap-3`}>
              <h2 id="unconfirmed-heading" ref={unconfirmedHeading} tabIndex={-1} className={`${SECTION_HEADING} outline-none`}>
                {t`Unconfirmed cells`}
              </h2>
              <p className="text-small text-ink-2">{t`These labels were sent to the printer, but nobody confirmed the result. Say what became of each one.`}</p>
              {unconfirmed.length >= 2 ? (
                <span className="flex flex-wrap gap-2">
                  <Button isDisabled={resolve.isPending || resolveAll.isPending} onPress={() => askResolveAll("printed")} className={SECONDARY_BUTTON}>
                    {t`Resolve all as printed`}
                  </Button>
                  <Button isDisabled={resolve.isPending || resolveAll.isPending} onPress={() => askResolveAll("not_printed")} className={SECONDARY_BUTTON}>
                    {t`Resolve all as not printed`}
                  </Button>
                </span>
              ) : null}
              <ul className="m-0 flex list-none flex-col gap-3 p-0">
                {unconfirmed.map((c) => {
                  const n = c.cell;
                  return (
                    <li key={n} className="flex min-w-0 flex-col gap-2">
                      <span className="text-small [overflow-wrap:anywhere]">{cellLine(c)}</span>
                      <span className="flex flex-wrap gap-2">
                        <Button
                          isDisabled={resolve.isPending || resolveAll.isPending}
                          aria-label={t`Printed, cell ${n}`}
                          onPress={() => resolve.mutate({ code, cells: [n], outcome: "printed" }, { onError: reload })}
                          className={SECONDARY_BUTTON}
                        >
                          {t({ message: "Printed", context: "resolve an unconfirmed cell" })}
                        </Button>
                        <Button
                          isDisabled={resolve.isPending || resolveAll.isPending}
                          aria-label={t`Not printed, cell ${n}`}
                          onPress={() => resolve.mutate({ code, cells: [n], outcome: "not_printed" }, { onError: reload })}
                          className={SECONDARY_BUTTON}
                        >
                          {t({ message: "Not printed", context: "resolve an unconfirmed cell" })}
                        </Button>
                      </span>
                    </li>
                  );
                })}
              </ul>
              {resolve.isError ? (
                <p role="alert" className="font-bold text-bad">
                  {errorText(resolve.error, t`The cell could not be resolved.`)}
                </p>
              ) : null}
            </section>
          ) : null}
        </aside>

        <div className="flex min-w-0 flex-col gap-4 lg:col-start-1 lg:row-start-1">
          <SheetGrid
            geometry={sheet.geometry}
            cells={gridCells}
            mode={mode === "view" ? "view" : "select"}
            onToggle={toggle}
            onInspect={setInspected}
            selectable={selectable}
            label={code}
          />

          {/* The one live region of the cell line: always in the page, so that a change in it is announced. */}
          <p
            role="status"
            aria-label={t`Selected cell`}
            className={inspected === null ? "" : "rounded-r2 bg-sunken px-3 py-2 [overflow-wrap:anywhere]"}
          >
            {inspected === null ? null : inspectedCell && !isChosen ? (
              <>
                {cellLine(inspectedCell)}
                {inspectedCell.state !== "used" ? <> ({cellStateWord(inspectedCell.state, translate)})</> : null}
              </>
            ) : isChosen ? (
              t`Cell ${inspected} is chosen`
            ) : (
              t`Cell ${inspected} is free`
            )}
          </p>

          {mode !== "view" ? (
            <section aria-labelledby="mode-heading" className={`${PANEL} flex flex-col gap-3`}>
              <h2 id="mode-heading" className={SECTION_HEADING}>
                {mode === "mark" ? t`Mark cells as used` : t`Un-mark cells`}
              </h2>
              <p className="text-small text-ink-2">
                {mode === "mark"
                  ? t`Tap the free labels that are gone. They are written down as marked by hand.`
                  : t`Only cells you marked by hand can be un-marked. Labels a job printed stay used.`}
              </p>
              {mode === "mark" ? (
                <TextInput label={t`Purpose (optional)`} value={purpose} onChange={setPurpose} maxLength={MAX_PURPOSE} description={t`Applies to every chosen cell.`} />
              ) : null}
              <p aria-live="polite" className="text-small font-bold">
                {chosen.length === 0 ? t`Nothing chosen yet` : plural(chosen.length, { one: "# cell chosen", other: "# cells chosen" })}
              </p>
              {writing.isError ? (
                <p role="alert" className="font-bold text-bad">
                  {errorText(writing.error, mode === "mark" ? t`The cells could not be marked.` : t`The cells could not be un-marked.`)}
                </p>
              ) : null}
              <div className="flex flex-wrap gap-3">
                <Button
                  isDisabled={chosen.length === 0 || writing.isPending}
                  onPress={mode === "mark" ? submitMark : submitUnmark}
                  className={PRIMARY_BUTTON}
                >
                  {mode === "mark"
                    ? plural(chosen.length, { one: "Mark # cell as used", other: "Mark # cells as used" })
                    : plural(chosen.length, { one: "Un-mark # cell", other: "Un-mark # cells" })}
                </Button>
                <Button onPress={leave} className={SECONDARY_BUTTON}>
                  {t`Cancel`}
                </Button>
              </div>
            </section>
          ) : null}

          {sheet.cells.length > 0 ? (
            <section aria-labelledby="cells-heading" className="flex min-w-0 flex-col gap-2">
              <h2 id="cells-heading" className={SECTION_HEADING}>
                {t`Cells in use`}
              </h2>
              {sheet.cells.length > LONG_LIST ? (
                <details>
                  <summary className="min-h-11 cursor-pointer py-2.5 text-link">
                    {plural(sheet.cells.length, { one: "Show the # cell", other: "Show all # cells" })}
                  </summary>
                  {cellList}
                </details>
              ) : (
                cellList
              )}
            </section>
          ) : (
            <p className="text-ink-2">{t`No cell is in use.`}</p>
          )}

          <details className="text-small">
            <summary className="min-h-11 cursor-pointer py-2.5 text-link">{t`What the markings mean`}</summary>
            <SheetLegend />
          </details>
        </div>
      </div>

      {canEdit ? (
        <ModalDialog
          title={
            resolvingAll?.outcome === "not_printed"
              ? plural(resolvingAll.count, { one: "Resolve # cell as not printed?", other: "Resolve # cells as not printed?" })
              : plural(resolvingAll?.count ?? 0, { one: "Resolve # cell as printed?", other: "Resolve # cells as printed?" })
          }
          isOpen={resolvingAll !== null}
          onClose={() => setResolvingAll(null)}
          alert
        >
          <p>
            {resolvingAll?.outcome === "not_printed"
              ? t`These labels are not on the sheet. The cells become free again.`
              : t`These labels are on the sheet. The cells stay marked as used.`}
          </p>
          <div className="flex flex-wrap gap-3">
            <Button isDisabled={resolveAll.isPending} onPress={confirmResolveAll} className={PRIMARY_BUTTON}>
              {resolvingAll?.outcome === "not_printed" ? t`Resolve as not printed` : t`Resolve as printed`}
            </Button>
            <Button onPress={() => setResolvingAll(null)} className={SECONDARY_BUTTON}>
              {t`Cancel`}
            </Button>
          </div>
        </ModalDialog>
      ) : null}

      {canEdit ? (
        <DiscardDialog
          sheet={discarding ? sheet : null}
          onClose={() => setDiscarding(false)}
          onShowUnconfirmed={() => setTimeout(() => unconfirmedHeading.current?.focus(), 0)}
        />
      ) : null}
    </div>
  );
}

/** `/sheets/$code` and `/sheet/$code` (the path printed in the sheet's QR code). */
export function SheetDetail() {
  const { t } = useLingui();
  const { code = "" } = useParams({ strict: false });
  const session = useSession();
  const errorText = useSheetErrorText();
  const sheet = useSheet(code);
  const canWrite = session.scope === "print" || session.scope === "admin";

  if (sheet.isPending) return <p className="text-ink-2">{t`Loading…`}</p>;
  if (sheet.isError || !sheet.data) {
    const missing = sheet.error instanceof ApiError && (sheet.error.status === 404 || sheet.error.code === "sheet_not_found");
    return (
      <div className="flex flex-col items-start gap-3">
        <h1 className="font-mono text-title font-bold [overflow-wrap:anywhere]">{code}</h1>
        <p role={missing ? undefined : "alert"}>{missing ? t`That sheet does not exist.` : errorText(sheet.error, t`The sheet could not be loaded.`)}</p>
        <Link to="/sheets" className={`${SECONDARY_BUTTON} no-underline`}>
          {t`Back to the sheets`}
        </Link>
      </div>
    );
  }
  return <SheetBody key={sheet.data.code} sheet={sheet.data} canWrite={canWrite} />;
}
