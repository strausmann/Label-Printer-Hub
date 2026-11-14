// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { plural } from "@lingui/core/macro";
import { useLingui } from "@lingui/react/macro";
import { useMemo } from "react";
import { Button } from "react-aria-components";
import { SECONDARY_BUTTON } from "../../ui";
import type { SheetPreview as PreviewData } from "../api";
import type { GridCell } from "../cellState";
import { SheetGrid, SheetLegend } from "../SheetGrid";
import { useSheetIdBand } from "./bandWord";

type Page = PreviewData["pages"][number];

/** More planned cells than this and the list of them starts folded. */
const LONG_LIST = 12;

export interface SheetPreviewProps {
  data: PreviewData;
  /** The name on the label of each item, by item index (every copy is an item). */
  itemName: (index: number) => string;
  zoom: 1 | 2;
  /** Cells the first page leaves out (`skip`); tapping a planned cell toggles it. Only the first page of an existing sheet. */
  skipped: readonly number[];
  onToggleSkip?: ((cell: number) => void) | undefined;
}

const numbers = (cells: number[]) => cells.join(", ");

function toGridCells(page: Page, skipped: readonly number[]): GridCell[] {
  return page.cells.map((c) => ({
    cell: c.cell,
    state: c.state === "free" && skipped.includes(c.cell) ? "skipped" : c.state,
    ...(c.purpose ? { purpose: c.purpose } : {}),
    isId: c.is_id,
    truncated: c.truncated,
    mapped: c.mapped,
    hwMargin: c.hw_margin,
  }));
}

function PageView({
  page,
  index,
  total,
  freeAfter,
  data,
  itemName,
  zoom,
  skipped,
  onToggleSkip,
}: { page: Page; index: number; total: number; freeAfter: number | undefined } & Omit<SheetPreviewProps, "zoom"> & { zoom: 1 | 2 }) {
  const { t, i18n } = useLingui();
  const sheetIdBand = useSheetIdBand();
  const number = index + 1;
  const code = page.sheet_code;
  const hint = page.new_code_hint ?? "";
  const heading = code
    ? t`Page ${number} of ${total}: ${code}`
    : hint
      ? t`Page ${number} of ${total}: a new sheet, probably ${hint}`
      : t`Page ${number} of ${total}: a new sheet`;
  const skippable = !!code && onToggleSkip !== undefined && index === 0;
  const cells = useMemo(() => toGridCells(page, skippable ? skipped : []), [page, skipped, skippable]);
  const fresh = page.cells.filter((c) => c.state === "new");
  const counts = {
    used: page.cells.filter((c) => c.state === "used").length,
    reserved: page.cells.filter((c) => c.state === "reserved").length,
    unconfirmed: page.cells.filter((c) => c.state === "unconfirmed").length,
    now: fresh.length,
  };
  const name = (c: Page["cells"][number]) => c.purpose || (c.item_index !== null ? itemName(c.item_index) : "");
  const hints = data.reprint_hints.filter((h) => fresh.some((c) => c.item_index === h.item_index));
  const mapped = numbers(fresh.filter((c) => c.mapped).map((c) => c.cell));
  const shortened = numbers(fresh.filter((c) => c.truncated).map((c) => c.cell));
  const cutOff = numbers(fresh.filter((c) => c.hw_margin).map((c) => c.cell));
  const { used, reserved, unconfirmed, now } = counts;
  const list = (
    <ul className="flex flex-col gap-0.5 text-small">
      {fresh.map((c) => {
        const cell = c.cell;
        const label = name(c);
        return <li key={cell} className="[overflow-wrap:anywhere]">{t`Cell ${cell} → ${label}`}</li>;
      })}
    </ul>
  );
  const pageSize = page.geometry.page_size;

  return (
    <article className="flex min-w-0 flex-col gap-3" aria-label={heading}>
      <h4 className="font-bold [overflow-wrap:anywhere]">{heading}</h4>
      <p className="flex flex-wrap gap-x-4 gap-y-1 text-small tabular-nums text-ink-2">
        <span>{t`${used} used`}</span>
        <span className="font-bold text-ink">{t`${now} printed now`}</span>
        {freeAfter !== undefined && <span>{t`${freeAfter} free afterwards`}</span>}
        {reserved > 0 && <span>{t`${reserved} reserved`}</span>}
        {unconfirmed > 0 && <span>{t`${unconfirmed} unconfirmed`}</span>}
      </p>
      <SheetGrid
        geometry={page.geometry}
        cells={cells}
        mode={skippable ? "skip" : "view"}
        zoom={zoom}
        label={code ?? t`New sheet`}
        overlayPng={`data:image/png;base64,${page.png_base64}`}
        {...(skippable ? { onToggle: onToggleSkip, selectable: (c: GridCell) => c.state === "new" || c.state === "skipped" } : {})}
      />
      <SheetLegend />
      {skippable && <p className="text-small text-ink-2">{t`Tap a planned cell to leave it out, for example a damaged label.`}</p>}

      <ul className="m-0 flex list-none flex-col gap-1 p-0 text-small">
        {page.feed_mark && <li className="flex items-center gap-2"><span aria-hidden="true">▲</span>{t`Top-edge mark`}</li>}
        {page.margin_id && <li>{sheetIdBand(page.margin_band)}</li>}
      </ul>
      {page.id_not_printed && <p className="font-bold text-warn">{t`Sheet ID not printed, add it by hand`}</p>}

      {fresh.length > LONG_LIST ? (
        <details>
          <summary className="min-h-11 cursor-pointer py-2 font-bold">{plural(fresh.length, { one: "Show the # cell", other: "Show the # cells" })}</summary>
          {list}
        </details>
      ) : (
        list
      )}

      <ul className="m-0 flex list-none flex-col gap-1 p-0 text-small">
        {mapped !== "" && (
          <li>
            <strong>{t`Code only on this sheet type`}</strong> <span className="text-ink-2">{t`cells ${mapped}`}</span>
          </li>
        )}
        {shortened !== "" && <li>{t`Text shortened to fit: cells ${shortened}`}</li>}
        {cutOff !== "" && <li>{t`May be cut off by the printer's unprintable margin: cells ${cutOff}`}</li>}
        {hints.map((h) => {
          const item = itemName(h.item_index);
          const where = h.sheet_code;
          const cell = h.cell;
          const when = new Date(h.printed_at).toLocaleDateString(i18n.locale, { dateStyle: "medium" });
          return <li key={`${h.item_index}-${where}-${cell}`}>{t`${item} was already printed onto ${where}, cell ${cell} (${when}).`}</li>;
        })}
      </ul>

      {page.load_hint && <p className="rounded-r2 bg-sunken p-3 [overflow-wrap:anywhere]">{page.load_hint}</p>}
      <p className="text-small text-ink-2">{t`PDF on ${pageSize}, media type labels, no scaling`}</p>
    </article>
  );
}

/** The server's plan, page by page: the rendered page with the cells over it, what is printed now, and what to watch for. */
export function SheetPreview(props: SheetPreviewProps) {
  const { data } = props;
  return (
    <div className="flex flex-col gap-6">
      {data.pages.map((page, index) => (
        <PageView
          key={`${index}-${page.sheet_code ?? "new"}`}
          page={page}
          index={index}
          total={data.pages.length}
          freeAfter={data.free_after[index]}
          {...props}
        />
      ))}
    </div>
  );
}

/** The zoom switch of the preview: the whole page, or 200 % in a scroll container of its own. */
export function ZoomToggle({ zoom, onChange, className = "" }: { zoom: 1 | 2; onChange: (zoom: 1 | 2) => void; className?: string }) {
  const { t } = useLingui();
  return (
    <Button className={`${SECONDARY_BUTTON} ${className}`} onPress={() => onChange(zoom === 1 ? 2 : 1)}>
      {zoom === 1 ? t`Zoom to 200 %` : t`Whole page`}
    </Button>
  );
}
