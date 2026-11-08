import { plural } from "@lingui/core/macro";
import { useLingui } from "@lingui/react/macro";
import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import { useCallback, useEffect, useState } from "react";
import { Button } from "react-aria-components";
import { useSession } from "../../app/session";
import { PRIMARY_BUTTON } from "../../shell/SignIn";
import { Badge } from "../archive/fields";
import { ModalDialog, SelectField, SwitchField, TextInput } from "../settings/controls";
import { PANEL, SECONDARY_BUTTON } from "../ui";
import { useSheetTypes } from "../archive/api";
import { AddSheetDialog } from "./AddSheetDialog";
import { formatMm } from "./cellState";
import { useSheetErrorText } from "./errors";
import { MAX_CODE_SEARCH, parseSheetsSearch, type SheetsSearch } from "./search";
import { typeLabelWithKey } from "./typeLabel";
import { useDiscardSheet, useSheets, type SheetSummary } from "./api";

const ANY = "__any__";
const FILTER_DELAY_MS = 200;

export { parseSheetsSearch };

/** A sheet with no free cell left (reserved and unconfirmed cells are not free either). */
const isUsedUp = (s: SheetSummary) => s.state === "active" && s.free === 0;

/**
 * Typing in the code box waits a moment before it asks the server and before the address changes.
 * When the address changes from outside (a link, back and forward), the box follows it.
 */
function useTypedQuery(current: string | undefined, commit: (q: string | undefined) => void) {
  const [value, setValue] = useState(current ?? "");
  const typed = value.trim() === "" ? undefined : value.trim();
  const [seen, setSeen] = useState(current);
  // React's pattern for state that follows a changing input: set it while rendering, not in an effect.
  if (seen !== current) {
    setSeen(current);
    if (typed !== current) setValue(current ?? "");
  }
  useEffect(() => {
    if (typed === current) return;
    const timer = setTimeout(() => commit(typed), FILTER_DELAY_MS);
    return () => clearTimeout(timer);
  }, [typed, current, commit]);
  return [value, setValue] as const;
}

/**
 * Used, reserved and unconfirmed cells as one bar. It is a drawing: the numbers beside it say the
 * same in words, and colour is never the only difference (the segments differ in position).
 */
function UsageBar({ sheet }: { sheet: SheetSummary }) {
  const total = Math.max(sheet.total, 1);
  const part = (n: number) => Math.min(100, (n / total) * 100);
  const used = part(sheet.used);
  const reserved = part(sheet.reserved);
  const unconfirmed = part(sheet.unconfirmed);
  return (
    <svg viewBox="0 0 100 6" preserveAspectRatio="none" aria-hidden="true" className="block h-1.5 w-full overflow-hidden rounded-full">
      <rect width="100" height="6" className="fill-sunken" />
      <rect x="0" width={used} height="6" className="fill-ink-3" />
      <rect x={used} width={reserved} height="6" className="fill-accent" />
      <rect x={used + reserved} width={unconfirmed} height="6" className="fill-warn" />
    </svg>
  );
}

function Usage({ sheet }: { sheet: SheetSummary }) {
  const { t } = useLingui();
  const { used, total, free, reserved, unconfirmed } = sheet;
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <UsageBar sheet={sheet} />
      <p className="flex flex-wrap gap-x-3 text-small text-ink-2 tabular-nums">
        <span className="font-bold text-ink">{t`${used} of ${total} used`}</span>
        <span>{t`${free} free`}</span>
        {reserved > 0 ? <span>{t`${reserved} reserved`}</span> : null}
        {unconfirmed > 0 ? <span>{t`${unconfirmed} unconfirmed`}</span> : null}
      </p>
    </div>
  );
}

function LastUsed({ iso }: { iso: string | null }) {
  const { t, i18n } = useLingui();
  if (!iso) return <span className="text-small text-ink-2">{t`Not used yet`}</span>;
  const date = new Date(iso);
  return (
    <time dateTime={iso} title={date.toLocaleString(i18n.locale)} className="text-small text-ink-2">
      {date.toLocaleDateString(i18n.locale, { dateStyle: "medium" })}
    </time>
  );
}

function StateWord({ sheet }: { sheet: SheetSummary }) {
  const { t } = useLingui();
  if (sheet.state === "discarded") return <Badge tone="warn">{t({ message: "discarded", context: "sheet state" })}</Badge>;
  if (isUsedUp(sheet)) return <Badge>{t({ message: "used up", context: "sheet state" })}</Badge>;
  return null;
}

/** The question before a discard, in the mockup's words, with the two traps of the server's rules. */
function DiscardDialog({ sheet, onClose }: { sheet: SheetSummary | null; onClose: () => void }) {
  const { t } = useLingui();
  const errorText = useSheetErrorText();
  const discard = useDiscardSheet();
  const code = sheet?.code ?? "";

  function close() {
    discard.reset();
    onClose();
  }

  return (
    <ModalDialog title={t`Discard sheet`} isOpen={sheet !== null} onClose={close} alert>
      <p>{t`Discard ${code}? It leaves the picker; its number is never given out again; labels already printed stay printed.`}</p>
      {sheet && sheet.unconfirmed > 0 ? (
        <div className="flex flex-col gap-1.5">
          <p>
            {plural(sheet.unconfirmed, {
              one: "Resolve the # unconfirmed cell first; once the sheet is discarded it can no longer be cleaned up.",
              other: "Resolve the # unconfirmed cells first; once the sheet is discarded they can no longer be cleaned up.",
            })}
          </p>
          <Link
            to="/sheets/$code"
            params={{ code: sheet.code }}
            className="inline-flex min-h-11 items-center self-start text-link underline underline-offset-2"
          >
            {t`Show the unconfirmed cells`}
          </Link>
        </div>
      ) : null}
      {discard.isError ? (
        <p role="alert" className="font-bold text-bad">
          {errorText(discard.error, t`The sheet could not be discarded.`)}
        </p>
      ) : null}
      <div className="flex flex-wrap gap-3">
        <Button
          isDisabled={discard.isPending}
          onPress={() => discard.mutate(code, { onSuccess: close })}
          className={PRIMARY_BUTTON}
        >
          {t`Discard sheet`}
        </Button>
        <Button onPress={close} className={SECONDARY_BUTTON}>
          {t`Cancel`}
        </Button>
      </div>
    </ModalDialog>
  );
}

const COLUMNS = "md:grid-cols-[7.5rem_minmax(0,1fr)_minmax(11rem,15rem)_7rem_6.5rem]";

function SheetRow({ sheet, canWrite, onDiscard }: { sheet: SheetSummary; canWrite: boolean; onDiscard: (s: SheetSummary) => void }) {
  const { t, i18n } = useLingui();
  const code = sheet.code;
  const size = `${formatMm(sheet.label_w, i18n.locale).replace(/ mm$/, "")} × ${formatMm(sheet.label_h, i18n.locale)}`;
  const typeLine = `${sheet.type_label} · ${size}`;
  const inUse = sheet.reserved > 0;
  const dim = sheet.state === "discarded";
  return (
    <div
      role="row"
      className={`grid min-w-0 grid-cols-[minmax(0,1fr)_auto] gap-x-4 gap-y-2 rounded-r2 border border-line bg-surface p-3 md:items-center md:rounded-none md:border-0 md:border-t md:bg-transparent md:px-3 md:py-2.5 ${COLUMNS} ${
        dim ? "text-ink-2" : ""
      }`}
    >
      <div role="cell" className="flex min-w-0 flex-wrap items-center gap-2 max-md:col-start-1 max-md:row-start-1">
        <Link
          to="/sheets/$code"
          params={{ code }}
          className="inline-flex min-h-11 items-center font-mono font-bold text-link underline underline-offset-2 focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-link"
        >
          {code}
        </Link>
        <StateWord sheet={sheet} />
      </div>
      <div role="cell" title={typeLine} className="line-clamp-2 min-w-0 text-small [overflow-wrap:anywhere] max-md:col-span-2">
        {typeLine}
      </div>
      <div role="cell" className="min-w-0 max-md:col-span-2">
        <Usage sheet={sheet} />
      </div>
      <div role="cell" className="max-md:col-span-2">
        <LastUsed iso={sheet.last_used_at} />
      </div>
      <div role="cell" className="flex min-w-0 items-center justify-end max-md:col-start-2 max-md:row-start-1">
        {!canWrite || dim ? null : inUse ? (
          <span className="text-small text-ink-2">{t`In use by a running job`}</span>
        ) : (
          <Button onPress={() => onDiscard(sheet)} aria-label={t`Discard ${code}`} className={`${SECONDARY_BUTTON} px-3`}>
            {t({ message: "Discard", context: "sheet action" })}
          </Button>
        )}
      </div>
    </div>
  );
}

/** `/sheets`: my sheets — what is left on each, and the ways to add one or retire one. */
export function SheetsPage() {
  const { t } = useLingui();
  const session = useSession();
  const canWrite = session.scope === "print" || session.scope === "admin";
  const search = useSearch({ strict: false }) as SheetsSearch;
  const navigate = useNavigate();
  const [adding, setAdding] = useState(false);
  const [discarding, setDiscarding] = useState<SheetSummary | null>(null);
  // On a phone the filters take the first screen: they start folded unless one is in use.
  const [filtersOpen, setFiltersOpen] = useState(() => Boolean(search.type || search.q || search.full || search.discarded));

  const commit = useCallback(
    (next: Partial<SheetsSearch>) => void navigate({ to: "/sheets", search: (prev) => ({ ...prev, ...next }), replace: true }),
    [navigate],
  );
  const commitQ = useCallback((q: string | undefined) => commit({ q }), [commit]);
  const [q, setQ] = useTypedQuery(search.q, commitQ);

  // "Active" still holds the sheets that are full, and there is no server filter for "has room":
  // the page hides the used-up sheets itself. Discarded sheets are asked for only when wanted.
  const list = useSheets({ type: search.type, q: search.q, state: search.discarded ? "all" : "active" });
  const types = useSheetTypes();
  const typeOptions = [{ id: ANY, label: t`Any sheet type` }, ...(types.data ?? []).map((x) => ({ id: x.key, label: typeLabelWithKey(x) }))];
  if (search.type && !typeOptions.some((o) => o.id === search.type)) typeOptions.push({ id: search.type, label: search.type });

  const hideUsedUp = search.full !== true;
  const rows = (list.data ?? []).filter((s) => !(hideUsedUp && isUsedUp(s)));
  const hidden = hideUsedUp ? (list.data ?? []).filter(isUsedUp).length : 0;
  const narrowed = Boolean(search.type || search.q);
  const activeFilters = [search.type, search.q, search.full, search.discarded].filter(Boolean).length;

  return (
    <div className="flex min-w-0 flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-title font-bold">{t`Sheets`}</h1>
        <div className="flex flex-wrap gap-3">
          <Link to="/sheets/archive" className={`${SECONDARY_BUTTON} no-underline`}>
            {t`Sheet archive`}
          </Link>
          {canWrite ? (
            <Button onPress={() => setAdding(true)} className={PRIMARY_BUTTON}>
              {t`New sheet`}
            </Button>
          ) : null}
        </div>
      </div>

      <div className="flex min-w-0 flex-col gap-4">
        <Button
          aria-expanded={filtersOpen}
          aria-controls="sheet-filters"
          onPress={() => setFiltersOpen((open) => !open)}
          className={`${SECONDARY_BUTTON} w-full justify-between md:hidden`}
        >
          <span>{activeFilters > 0 ? t`Filters (${activeFilters} active)` : t`Filters`}</span>
          <svg viewBox="0 0 12 12" width="12" height="12" aria-hidden="true" className={`fill-none stroke-current stroke-2 transition-transform duration-150 ${filtersOpen ? "rotate-180" : ""}`}>
            <path d="M2 4.5 6 8.5 10 4.5" />
          </svg>
        </Button>
        <form
          id="sheet-filters"
          role="search"
          aria-label={t`Filter the sheets`}
          onSubmit={(e) => e.preventDefault()}
          className={`${PANEL} ${filtersOpen ? "grid" : "hidden"} gap-4 md:grid md:grid-cols-2 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto_auto] lg:items-end`}
        >
          <TextInput label={t`Search by code`} value={q} onChange={setQ} placeholder="L4736-0004" mono maxLength={MAX_CODE_SEARCH} />
          <SelectField
            label={t`Sheet type`}
            value={search.type ?? ANY}
            options={typeOptions}
            onChange={(id) => commit({ type: id === ANY ? undefined : id })}
          />
          <SwitchField label={t`Hide used-up sheets`} isSelected={hideUsedUp} onChange={(on) => commit({ full: on ? undefined : true })} />
          <SwitchField label={t`Show discarded sheets`} isSelected={search.discarded === true} onChange={(on) => commit({ discarded: on ? true : undefined })} />
        </form>
      </div>

      {list.isPending ? <p className="text-ink-2">{t`Loading…`}</p> : null}
      {list.isError ? <p role="alert">{t`The sheets could not be loaded.`}</p> : null}
      {list.data ? (
        <>
          {rows.length === 0 ? (
            <div className="flex flex-col items-start gap-3">
              <p className="text-ink-2">
                {narrowed ? t`No sheet matches.` : hidden > 0 ? t`Every sheet is used up.` : t`No sheets yet.`}
              </p>
              {narrowed ? (
                <Button onPress={() => commit({ type: undefined, q: undefined })} className={SECONDARY_BUTTON}>
                  {t`Clear filters`}
                </Button>
              ) : null}
            </div>
          ) : (
            <div role="table" aria-label={t`Sheets`} className="flex min-w-0 flex-col gap-2 md:gap-0">
              <div role="rowgroup" className="sr-only md:not-sr-only">
                <div role="row" className={`grid gap-x-4 px-3 pb-2 text-small font-bold text-ink-2 ${COLUMNS}`}>
                  <span role="columnheader">{t`Sheet`}</span>
                  <span role="columnheader">{t`Type`}</span>
                  <span role="columnheader">{t`Used`}</span>
                  <span role="columnheader">{t`Last used`}</span>
                  <span role="columnheader" className="text-right">{t`Action`}</span>
                </div>
              </div>
              <div role="rowgroup" className="flex flex-col gap-2 md:gap-0">
                {rows.map((sheet) => (
                  <SheetRow key={sheet.code} sheet={sheet} canWrite={canWrite} onDiscard={setDiscarding} />
                ))}
              </div>
            </div>
          )}
          {hidden > 0 ? (
            <p className="text-small text-ink-2">
              {plural(hidden, { one: "# used-up sheet hidden", other: "# used-up sheets hidden" })}{" "}
              <Button onPress={() => commit({ full: true })} className="inline-flex min-h-11 items-center text-link underline underline-offset-2">
                {t`Show them`}
              </Button>
            </p>
          ) : null}
        </>
      ) : null}

      {canWrite ? <AddSheetDialog isOpen={adding} onClose={() => setAdding(false)} /> : null}
      <DiscardDialog sheet={discarding} onClose={() => setDiscarding(null)} />
    </div>
  );
}
