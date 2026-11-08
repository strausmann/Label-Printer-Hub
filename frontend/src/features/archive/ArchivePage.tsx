import { plural } from "@lingui/core/macro";
import { useLingui } from "@lingui/react/macro";
import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import { useCallback, useEffect, useState } from "react";
import { Button } from "react-aria-components";
import { useSession } from "../../app/session";
import { PRIMARY_BUTTON } from "../../shell/SignIn";
import { formatMm } from "../sheets/cellState";
import { SelectField, SwitchField, TextInput } from "../settings/controls";
import { PANEL, SECONDARY_BUTTON } from "../ui";
import { useSheetTypes, type SheetTypeRead } from "./api";
import { ImportDialog } from "./ImportDialog";
import { parseDecimal, type ArchiveSearch } from "./search";
import { TypeBadges, TypeDetail } from "./TypeDetail";
import { TypeForm } from "./TypeForm";

const ANY = "__any__";
const FILTER_DELAY_MS = 200;

/** Typing in a filter waits a moment before it asks the server (and before the address changes). */
function useTypedFilters(search: ArchiveSearch, commit: (next: Partial<ArchiveSearch>) => void) {
  const [q, setQ] = useState(search.q ?? "");
  const [w, setW] = useState(search.w === undefined ? "" : String(search.w));
  const [h, setH] = useState(search.h === undefined ? "" : String(search.h));
  useEffect(() => {
    const size = (value: string) => {
      const n = parseDecimal(value);
      return n !== null && n > 0 && n <= 1000 ? n : undefined;
    };
    const next = { q: q.trim() === "" ? undefined : q.trim(), w: size(w), h: size(h) };
    if (next.q === search.q && next.w === search.w && next.h === search.h) return;
    const timer = setTimeout(() => commit(next), FILTER_DELAY_MS);
    return () => clearTimeout(timer);
  }, [q, w, h, search.q, search.w, search.h, commit]);
  return { q, setQ, w, setW, h, setH, clear: () => { setQ(""); setW(""); setH(""); } };
}

function TypeRow({ type, selected }: { type: SheetTypeRead; selected: boolean }) {
  const { i18n } = useLingui();
  const g = type.geometry;
  const mm = (v: number) => formatMm(v, i18n.locale);
  return (
    <li>
      <Link
        to="/sheets/archive"
        search={(prev) => ({ ...prev, type: type.key })}
        aria-current={selected ? "true" : undefined}
        className={`press flex min-h-11 min-w-0 flex-col gap-1 rounded-r2 border p-3 no-underline transition-colors duration-150 focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-link ${
          selected ? "border-accent bg-accent-soft" : "border-line bg-surface hover:bg-sunken"
        }`}
      >
        <span className="font-bold text-ink [overflow-wrap:anywhere]">{type.key}</span>
        <span className="text-small text-ink-2 [overflow-wrap:anywhere]">
          {[type.vendor, type.description].filter(Boolean).join(" · ")}
        </span>
        <span className="text-small text-ink-2">
          {g.page_size} · {mm(g.label_w)} × {mm(g.label_h)} · {plural(g.cols * g.rows, { one: "# label", other: "# labels" })}
        </span>
        <TypeBadges type={type} />
      </Link>
    </li>
  );
}

/** `/sheets/archive`: the catalogue of sheet types, their versions, and (for admins) the ways to change them. */
export function SheetArchivePage() {
  const { t } = useLingui();
  const session = useSession();
  const admin = session.scope === "admin";
  const search = useSearch({ strict: false }) as ArchiveSearch;
  const navigate = useNavigate();
  const [creating, setCreating] = useState(false);
  const [importing, setImporting] = useState(false);

  const commit = useCallback(
    (next: Partial<ArchiveSearch>) => void navigate({ to: "/sheets/archive", search: (prev) => ({ ...prev, ...next }), replace: true }),
    [navigate],
  );
  const typed = useTypedFilters(search, commit);

  const list = useSheetTypes({
    page: search.page,
    vendor: search.vendor,
    q: search.q,
    w: search.w,
    h: search.h,
    include_archived: search.archived,
  });
  // The vendors to choose from come from the unfiltered list, so choosing one does not hide the others.
  const all = useSheetTypes({ include_archived: search.archived });
  const vendors = [...new Set((all.data ?? []).map((x) => x.vendor).filter((v): v is string => !!v))].sort((a, b) => a.localeCompare(b));
  if (search.vendor && !vendors.includes(search.vendor)) vendors.push(search.vendor);

  const filtered = Boolean(search.q || search.page || search.vendor || search.w || search.h);
  const open = search.type;

  return (
    <div className="flex min-w-0 flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-title font-bold">{t`Sheet archive`}</h1>
        {admin && !creating ? (
          <div className="flex flex-wrap gap-3">
            <Button onPress={() => setCreating(true)} className={PRIMARY_BUTTON}>{t`New type`}</Button>
            <Button onPress={() => setImporting(true)} className={SECONDARY_BUTTON}>{t`Import type`}</Button>
          </div>
        ) : null}
      </div>

      {creating ? (
        <TypeForm
          mode={{ kind: "create" }}
          onDone={(key) => {
            setCreating(false);
            if (key) void navigate({ to: "/sheets/archive", search: (prev) => ({ ...prev, type: key }) });
          }}
        />
      ) : (
        <div className="grid min-w-0 gap-8 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)] lg:items-start">
          <div className={`flex min-w-0 flex-col gap-4 ${open ? "hidden lg:flex" : ""}`}>
            <form role="search" aria-label={t`Filter the sheet types`} onSubmit={(e) => e.preventDefault()} className={`${PANEL} flex flex-col gap-4`}>
              <TextInput label={t`Search`} value={typed.q} onChange={typed.setQ} description={t`Key, description or product code`} />
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2">
                <SelectField
                  label={t`Page size`}
                  value={search.page ?? ANY}
                  options={[
                    { id: ANY, label: t`Any page size` },
                    { id: "A4", label: "A4" },
                    { id: "Letter", label: "Letter" },
                  ]}
                  onChange={(id) => commit({ page: id === "A4" || id === "Letter" ? id : undefined })}
                />
                <SelectField
                  label={t`Vendor`}
                  value={search.vendor ?? ANY}
                  options={[{ id: ANY, label: t`Any vendor` }, ...vendors.map((v) => ({ id: v, label: v }))]}
                  onChange={(id) => commit({ vendor: id === ANY ? undefined : id })}
                />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <TextInput label={t`Label width (mm)`} value={typed.w} onChange={typed.setW} inputMode="decimal" />
                <TextInput label={t`Label height (mm)`} value={typed.h} onChange={typed.setH} inputMode="decimal" />
              </div>
              <SwitchField label={t`Show archived types`} isSelected={search.archived === true} onChange={(on) => commit({ archived: on ? true : undefined })} />
              {filtered ? (
                <Button
                  onPress={() => {
                    typed.clear();
                    commit({ q: undefined, page: undefined, vendor: undefined, w: undefined, h: undefined });
                  }}
                  className={`${SECONDARY_BUTTON} self-start`}
                >
                  {t`Clear filters`}
                </Button>
              ) : null}
            </form>

            {list.isPending ? <p className="text-ink-2">{t`Loading…`}</p> : null}
            {list.isError ? <p role="alert">{t`The sheet types could not be loaded.`}</p> : null}
            {list.data ? (
              list.data.length === 0 ? (
                <p className="text-ink-2">{t`No sheet type matches.`}</p>
              ) : (
                <ul aria-label={t`Sheet types`} className="flex flex-col gap-2 lg:max-h-[65dvh] lg:overflow-y-auto lg:p-1">
                  {list.data.map((type) => (
                    <TypeRow key={type.key} type={type} selected={type.key === open} />
                  ))}
                </ul>
              )
            ) : null}
          </div>

          <div className="min-w-0">
            {open ? (
              <TypeDetail
                key={open}
                typeKey={open}
                admin={admin}
                onLeave={() => void navigate({ to: "/sheets/archive", search: (prev) => ({ ...prev, type: undefined }) })}
              />
            ) : (
              <p className="hidden text-ink-2 lg:block">{t`Choose a sheet type to see its measurements and versions.`}</p>
            )}
          </div>
        </div>
      )}

      {admin ? (
        <ImportDialog
          isOpen={importing}
          onClose={() => setImporting(false)}
          onShow={(key) => void navigate({ to: "/sheets/archive", search: (prev) => ({ ...prev, type: key }) })}
        />
      ) : null}
    </div>
  );
}
