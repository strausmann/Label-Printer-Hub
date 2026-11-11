import { plural } from "@lingui/core/macro";
import { useLingui } from "@lingui/react/macro";
import { Link } from "@tanstack/react-router";
import { useState } from "react";
import { Button } from "react-aria-components";
import { ApiError } from "../../api/client";
import { PRIMARY_BUTTON } from "../../shell/SignIn";
import { GeometryDiagram } from "../sheets/GeometryDiagram";
import { formatMm } from "../sheets/cellState";
import { ModalDialog } from "../settings/controls";
import { SECTION_HEADING, SECONDARY_BUTTON } from "../ui";
import { exportTypeUrl, useArchiveType, useDeleteType, useSheetType, type SheetTypeDetail } from "./api";
import { useArchiveErrorText } from "./errors";
import { Badge } from "./fields";
import { FeedbackLinks } from "./FeedbackLinks";
import { TypeForm } from "./TypeForm";
import { httpUrl } from "./search";

/** The words that mark a type: where it came from, whether anyone measured it, whether it is retired. */
export function TypeBadges({ type }: { type: { origin: "seed" | "custom" | "imported"; verified: boolean; archived_at: string | null } }) {
  const { t } = useLingui();
  const origin = { seed: t`seed`, custom: t`custom`, imported: t`imported` }[type.origin];
  return (
    <span className="flex flex-wrap gap-1.5">
      <Badge>{origin}</Badge>
      {type.verified ? null : <Badge tone="warn">{t`unverified`}</Badge>}
      {type.archived_at ? <Badge tone="warn">{t`archived`}</Badge> : null}
    </span>
  );
}

/** A few codes inline; a long list (the server allows 50) folds away behind its count. */
function ProductCodes({ codes }: { codes: string[] }) {
  const { t } = useLingui();
  if (codes.length === 0) return null;
  const list = <span className="font-mono text-small [overflow-wrap:anywhere]">{codes.join(", ")}</span>;
  if (codes.length <= 5) return <p className="text-small text-ink-2">{t`Product codes`}: {list}</p>;
  return (
    <details className="text-small text-ink-2">
      <summary className="min-h-11 cursor-pointer py-2.5">{plural(codes.length, { one: "# product code", other: "# product codes" })}</summary>
      {list}
    </details>
  );
}

function Source({ type }: { type: SheetTypeDetail }) {
  const url = httpUrl(type.source_url);
  const name = type.source_name;
  if (!name && !type.source_url) return null;
  return (
    <p>
      {url ? (
        <a href={url} target="_blank" rel="noopener noreferrer" className="text-link underline underline-offset-2 [overflow-wrap:anywhere]">
          {name ?? url}
        </a>
      ) : (
        <>
          {name ? <span>{name}</span> : null}
          {name && type.source_url ? " " : null}
          {type.source_url ? <span className="font-mono text-small text-ink-2 [overflow-wrap:anywhere]">{type.source_url}</span> : null}
        </>
      )}
    </p>
  );
}

function Versions({ type }: { type: SheetTypeDetail }) {
  const { t, i18n } = useLingui();
  const date = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString(i18n.locale) : "");
  return (
    <div className="-mx-4 overflow-x-auto px-4 sm:mx-0 sm:px-0">
      <table aria-label={t`Versions`} className="w-full min-w-0 border-collapse text-left">
        <thead>
          <tr className="text-small text-ink-2">
            <th scope="col" className="py-2 pr-3 font-bold">{t`Version`}</th>
            <th scope="col" className="py-2 pr-3 font-bold">{t`What changed`}</th>
            <th scope="col" className="py-2 text-right font-bold">{t`Sheets`}</th>
          </tr>
        </thead>
        <tbody>
          {[...type.versions].sort((a, b) => b.version - a.version).map((v) => (
            <tr key={v.version} className="border-t border-line align-top">
              <th scope="row" className="py-2 pr-3 whitespace-nowrap">
                {v.version}
                {v.version === type.current_version ? <span className="ml-2 text-small font-normal text-ink-2">{t`current`}</span> : null}
              </th>
              <td className="min-w-0 py-2 pr-3 [overflow-wrap:anywhere]">
                {v.change_note ?? <span className="text-ink-2">{t`first version`}</span>}
                {v.created_at ? <span className="block text-small text-ink-2">{date(v.created_at)}</span> : null}
                <a href={exportTypeUrl(type.key, v.version)} download className="inline-flex min-h-11 items-center text-small text-link underline underline-offset-2">
                  {t`Export version ${v.version}`}
                </a>
              </td>
              <td className="py-2 text-right tabular-nums">{v.sheets}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** One type in full: measurements, versions, provenance and (for admins) the actions. */
export function TypeDetail({ typeKey, admin, onLeave }: { typeKey: string; admin: boolean; onLeave: () => void }) {
  const { t, i18n } = useLingui();
  const errorText = useArchiveErrorText();
  const query = useSheetType(typeKey);
  const archive = useArchiveType();
  const remove = useDeleteType();
  const [editing, setEditing] = useState<"geometry" | "details" | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  if (query.isPending) return <p className="text-ink-2">{t`Loading…`}</p>;
  if (query.isError) {
    const gone = query.error instanceof ApiError && query.error.code === "sheet_type_not_found";
    return (
      <p role="alert" className="text-ink">
        {gone ? t`That sheet type does not exist.` : t`The sheet type could not be loaded.`}
      </p>
    );
  }
  const type = query.data;
  const archived = type.archived_at !== null;
  const canDelete = admin && type.origin === "custom" && type.sheets_in_use === 0;
  const actionError = archive.error ?? remove.error;
  const g = type.geometry;
  const mm = (v: number) => formatMm(v, i18n.locale);

  return (
    <article aria-label={type.key} className="flex min-w-0 flex-col gap-6">
      <Link to="/sheets/archive" search={(prev) => ({ ...prev, type: undefined })} className="inline-flex min-h-11 items-center text-link underline underline-offset-2 lg:hidden">
        {t`Back to the list`}
      </Link>
      <header className="flex flex-col gap-2">
        <h2 className="text-title font-bold [overflow-wrap:anywhere]">{type.key}</h2>
        <TypeBadges type={type} />
        <p className="text-ink-2 [overflow-wrap:anywhere]">
          {[type.vendor, type.description].filter(Boolean).join(" · ") || null}
        </p>
        <p className="text-small text-ink-2">
          {mm(g.label_w)} × {mm(g.label_h)} · {plural(g.cols * g.rows, { one: "# label", other: "# labels" })} ·{" "}
          {t`Code prefix`} <span className="font-mono">{type.prefix}</span>
        </p>
        <ProductCodes codes={type.product_codes} />
      </header>

      {editing ? (
        <TypeForm mode={{ kind: editing, type }} onDone={() => setEditing(null)} />
      ) : (
        <>
          <div className="flex flex-wrap gap-3">
            {admin ? (
              <>
                <Button onPress={() => setEditing("geometry")} className={PRIMARY_BUTTON}>{t`Edit geometry`}</Button>
                <Button onPress={() => setEditing("details")} className={SECONDARY_BUTTON}>{t`Edit details`}</Button>
              </>
            ) : null}
            <a href={exportTypeUrl(type.key)} download className={`${SECONDARY_BUTTON} no-underline`}>
              {t`Export`}
            </a>
            {admin ? (
              <Button
                isDisabled={archive.isPending}
                onPress={() => archive.mutate({ key: type.key, unarchive: archived })}
                className={SECONDARY_BUTTON}
              >
                {archived ? t`Unarchive` : t`Archive`}
              </Button>
            ) : null}
            {canDelete ? (
              <Button onPress={() => setConfirmDelete(true)} className={SECONDARY_BUTTON}>{t`Delete`}</Button>
            ) : null}
          </div>
          {actionError ? <p role="alert">{errorText(actionError)}</p> : null}

          <section aria-labelledby="geometry-heading" className="flex flex-col gap-3">
            <h3 id="geometry-heading" className={SECTION_HEADING}>{t`Measurements`}</h3>
            <GeometryDiagram geometry={g} hints={type.hints} />
            <p className="text-ink-2">{type.allow_qr ? t`QR codes on labels: allowed` : t`QR codes on labels: not allowed`}</p>
          </section>

          <section aria-labelledby="versions-heading" className="flex flex-col gap-3">
            <h3 id="versions-heading" className={SECTION_HEADING}>{t`Versions`}</h3>
            <Versions type={type} />
          </section>

          {type.source_name || type.source_url || type.notes ? (
            <section aria-labelledby="source-heading" className="flex flex-col gap-3">
              <h3 id="source-heading" className={SECTION_HEADING}>{t`Where the numbers come from`}</h3>
              <Source type={type} />
              {type.notes ? <p className="whitespace-pre-wrap text-ink-2 [overflow-wrap:anywhere]">{type.notes}</p> : null}
            </section>
          ) : null}

          <FeedbackLinks type={type} admin={admin} />
        </>
      )}

      <ModalDialog title={t`Delete this type?`} isOpen={confirmDelete} onClose={() => setConfirmDelete(false)} alert>
        <p>{t`${type.key} has no sheets. Deleting it removes it and all its versions for good.`}</p>
        <div className="flex flex-wrap gap-3">
          <Button
            isDisabled={remove.isPending}
            onPress={() =>
              remove.mutate(type.key, {
                onSuccess: () => {
                  setConfirmDelete(false);
                  onLeave();
                },
                onError: () => setConfirmDelete(false),
              })
            }
            className={PRIMARY_BUTTON}
          >
            {t`Delete type`}
          </Button>
          <Button onPress={() => setConfirmDelete(false)} className={SECONDARY_BUTTON}>{t`Cancel`}</Button>
        </div>
      </ModalDialog>
    </article>
  );
}
