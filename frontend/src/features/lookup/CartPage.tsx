// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { plural } from "@lingui/core/macro";
import { useLingui } from "@lingui/react/macro";
import { getRouteApi, Link } from "@tanstack/react-router";
import { useState } from "react";
import { Button } from "react-aria-components";
import { useSession } from "../../app/session";
import { FIELD, PRIMARY_BUTTON } from "../../shell/SignIn";
import { LayoutPicker } from "../layout/LayoutPicker";
import { tapeMmOfStatus, useLabelLayout, type LayoutOptions } from "../layout/ql";
import { usePrinters, usePrinterStatus, usePrinterStatuses } from "../printers/api";
import { HINT } from "../settings/controls";
import { PANEL, SECONDARY_BUTTON } from "../ui";
import { useAppName, useContentTypeLabel } from "./apps";
import { useLookup, usePreviewImage, type LookupResult } from "./api";
import { BatchStatusError, MAX_COPIES, useCart, type BatchRead, type CartItem, type ContentType } from "./cart";
import { distinctPreviews, itemKey } from "./cartPreviews";
import { LabelPreview } from "./LabelPreview";
import { useCartCheck, type RenderCheckResult } from "./useCartCheck";
import { PrinterPicker, usePrinterChoice, usePrintErrorText } from "./PrinterPicker";
import { SheetSection } from "../sheets/print/SheetSection";

const cartApi = getRouteApi("/cart");

/** One item of the cart as the layout will print it. The print looks the item up again, so this is a close picture. */
function CartPreview({ item, tapeMm, layout }: { item: CartItem; tapeMm: number; layout: LayoutOptions | undefined }) {
  const { t } = useLingui();
  const contentTypeLabel = useContentTypeLabel();
  const lookup = useLookup(item.app, item.id);
  const name = item.name;
  const kind = contentTypeLabel(item.content_type);
  return (
    <section aria-label={t`Preview of ${name}`} className="flex flex-col gap-2">
      {lookup.data ? (
        <CartPreviewImage
          item={lookup.data}
          contentType={item.content_type}
          tapeMm={tapeMm}
          layout={item.content_type === "spool_swatch" ? undefined : layout}
        />
      ) : (
        <p role={lookup.isError ? undefined : "status"} className="text-ink-2">
          {lookup.isError ? t`No preview available.` : t`Drawing the label…`}
        </p>
      )}
      <p className="text-small text-ink-2">{t`${kind}, for example ${name}.`}</p>
    </section>
  );
}

function CartPreviewImage({ item, contentType, tapeMm, layout }: { item: LookupResult; contentType: ContentType; tapeMm: number; layout: LayoutOptions | undefined }) {
  return <LabelPreview preview={usePreviewImage(item, contentType, tapeMm, true, layout)} layout={layout} />;
}

/** One preview per content type: the labels of one type look alike, so the batch is shown by its different layouts. */
function CartPreviews({ items, tapeMm, layout }: { items: CartItem[]; tapeMm: number; layout: LayoutOptions | undefined }) {
  const { t } = useLingui();
  const { shown, hiddenTypes } = distinctPreviews(items);
  return (
    <div className="flex flex-col gap-4">
      <h3 className="font-bold">{t`Preview`}</h3>
      {shown.map((item) => (
        <CartPreview key={item.content_type} item={item} tapeMm={tapeMm} layout={layout} />
      ))}
      {hiddenTypes > 0 && <p className="text-small text-ink-2">{plural(hiddenTypes, { one: "# more layout is not shown.", other: "# more layouts are not shown." })}</p>}
    </div>
  );
}

/** What is wrong with one item, in words; the server's English sentence is only the last resort. */
function useFlagText(): (result: RenderCheckResult) => string {
  const { t } = useLingui();
  return (result) => {
    switch (result.error_code) {
      case "qr_payload_too_long": {
        const length = Number(result.error_detail?.length);
        const max = Number(result.error_detail?.max_bytes);
        return Number.isFinite(length) && Number.isFinite(max)
          ? t`The QR code does not fit this tape: ${length} of at most ${max} bytes.`
          : t`The QR code does not fit this tape.`;
      }
      case "content_type_data_mismatch":
        return t`This item has no data for this layout.`;
      case "render_failed":
        return t`The label could not be drawn for this tape.`;
      case "integration_item_not_found":
        return t`This item no longer exists in its app.`;
      case "integration_not_configured":
        return t`The app of this item is not set up.`;
      case "integration_unknown_app":
        return t`The app of this item is not known.`;
      case "integration_lookup_failed":
        return t`The app of this item did not answer.`;
      default:
        return result.error_message ?? t`This label cannot be drawn.`;
    }
  };
}

type Outcome = { kind: "sent"; labels: number; printer: string; batch: BatchRead | null } | { kind: "failed"; error: unknown };

/** The cart: everything collected from item views, printed as ONE batch (ADR 0013). */
export function CartPage() {
  const { t } = useLingui();
  const appName = useAppName();
  const errorText = usePrintErrorText();
  // A read key fills the cart but may not print it: say so before the press, not with a 403 after it.
  const readOnly = useSession().scope === "read";
  const cart = useCart();
  const printers = usePrinters();
  const { usable, selected, choose } = usePrinterChoice(printers.data);
  const statuses = usePrinterStatuses(usable);
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  // `/cart?sheet=<code>` (the link from a sheet's page) preselects that sheet in the sheet section.
  const { sheet: linkedSheet, tray: linkedTray } = cartApi.useSearch();
  // The cart empties when the hub accepts a sheet print, or queues all of it before a partial failure; the section
  // stays to show where the labels went (the result, or the partial-result note with the links to the queued jobs).
  const [sheetPrinted, setSheetPrinted] = useState(false);
  const pagePrinter = selected?.backend === "ipp";
  const status = usePrinterStatus(selected?.id ?? "", !!selected && !pagePrinter);
  const tapeMm = tapeMmOfStatus(selected ? status.data : null);
  const layout = useLabelLayout(selected, tapeMm);
  // A check needs a tape the printer reported; the 12 mm fallback of `tapeMmOfStatus` would flag items against a guess.
  const tapeKnown = !!selected && !pagePrinter && (typeof status.data?.tape_width_mm === "number" || !!status.data?.tape_loaded);
  const check = useCartCheck(cart.items, tapeKnown ? tapeMm : null, layout.active ? layout.options : undefined);
  const flagText = useFlagText();
  const failing = cart.items.filter((i) => check.flags.get(itemKey(i))?.ok === false);
  const labels = cart.items.reduce((sum, i) => sum + i.copies, 0);
  const allSwatch = cart.items.length > 0 && cart.items.every((i) => i.content_type === "spool_swatch");

  const send = async () => {
    if (!selected) return;
    const count = labels;
    setBusy(true);
    try {
      const batch = await cart.print(selected.id, layout.options);
      setOutcome({ kind: "sent", labels: count, printer: selected.name, batch });
    } catch (error) {
      // The labels are queued even though their status could not be read.
      setOutcome(error instanceof BatchStatusError ? { kind: "sent", labels: count, printer: selected.name, batch: null } : { kind: "failed", error });
    } finally {
      setBusy(false);
    }
  };

  const sent = outcome?.kind === "sent" ? outcome : null;
  const sentLabels = sent?.labels ?? 0;
  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-title font-bold">{t`Cart`}</h1>

      {sent && (
        <p role="status" className={`${PANEL}`}>
          {plural(sentLabels, { one: "# label sent to", other: "# labels sent to" })} {sent.printer}.{" "}
          <Link to="/jobs" className="text-link underline underline-offset-2">
            {t`See the jobs`}
          </Link>
        </p>
      )}

      {cart.items.length === 0 && (!sheetPrinted || !pagePrinter) && (
        <>
          <p className="text-ink-2">{t`The cart is empty.`}</p>
          {linkedSheet && (
            <p className="text-ink-2">{t`Add items to print onto ${linkedSheet}.`}</p>
          )}
        </>
      )}

      {(cart.items.length > 0 || sheetPrinted) && (
        <>
          {cart.items.length > 0 && <ul aria-label={t`Cart`} className="flex flex-col gap-2">
            {cart.items.map((item) => {
              const itemName = item.name;
              const flag = check.flags.get(itemKey(item));
              const flagged = flag && !flag.ok ? flag : null;
              const flagId = `cart-flag-${item.app}-${item.id}`;
              return (
              <li key={`${item.app}:${item.id}`} aria-describedby={flagged ? flagId : undefined} className="grid gap-3 rounded-r3 border border-line bg-surface p-4 sm:grid-cols-[minmax(0,1fr)_auto_auto] sm:items-center">
                <span className="flex min-w-0 flex-col">
                  <Link
                    to="/lookup/$app/$id"
                    params={{ app: item.app, id: item.id }}
                    className="truncate font-bold text-link underline underline-offset-2"
                  >
                    {item.name}
                  </Link>
                  <span className="text-small text-ink-2">
                    {appName(item.app)} · <code className="break-all text-ink">{item.id}</code>
                  </span>
                  {flagged && <span id={flagId} className="mt-1 text-small text-bad">{flagText(flagged)}</span>}
                </span>
                <label className="flex items-center gap-2 text-small">
                  <span>{t`Copies`}</span>
                  <input
                    type="number"
                    inputMode="numeric"
                    min={1}
                    max={MAX_COPIES}
                    value={item.copies}
                    aria-label={t`Copies of ${itemName}`}
                    className={`${FIELD} code w-20`}
                    onChange={(e) => cart.setCopies(item, Number(e.target.value))}
                  />
                </label>
                <Button className={SECONDARY_BUTTON} aria-label={t`Remove ${itemName}`} onPress={() => cart.remove(item)}>
                  {t`Remove`}
                </Button>
              </li>
              );
            })}
          </ul>}

          <section aria-labelledby="cart-print-h" className={`${PANEL} flex max-w-md flex-col gap-4`}>
            <h2 id="cart-print-h" className="text-section font-bold">{t`Print`}</h2>
            <PrinterPicker printers={usable} value={selected?.id ?? null} onChange={choose} loading={printers.isPending} statuses={statuses} />
            {layout.active && (
              <>
                {/* A cart of spool labels only has nothing to turn or arrange (#346). */}
                {!allSwatch && (
                  <LayoutPicker
                    orientation={layout.choice.orientation}
                    preset={layout.choice.preset}
                    onOrientation={layout.setOrientation}
                    onPreset={layout.setPreset}
                  />
                )}
                {cart.items.length > 0 && <CartPreviews items={cart.items} tapeMm={tapeMm} layout={layout.options} />}
              </>
            )}
            {failing.length > 0 && (
              <p role="status" className="m-0 font-bold text-bad">
                {plural(failing.length, { one: "# item will not print.", other: "# items will not print." })}
              </p>
            )}
            {check.isError && <p className={`${HINT} m-0`}>{t`Could not check the items; the print still checks them.`}</p>}
            <div className="flex flex-wrap gap-2">
              {/* A page printer prints through the sheet section below. */}
              {/* An emptied cart (a sheet print took everything out) leaves nothing to send. */}
              {!pagePrinter && cart.items.length > 0 && (
                <Button className={PRIMARY_BUTTON} isDisabled={!selected || busy || readOnly} onPress={() => void send()}>
                  {plural(labels, { one: "Print # label", other: "Print # labels" })}
                </Button>
              )}
              {cart.items.length > 0 && (
                <Button className={SECONDARY_BUTTON} isDisabled={busy} onPress={cart.clear}>
                  {t`Empty the cart`}
                </Button>
              )}
            </div>
            {readOnly && !pagePrinter && cart.items.length > 0 && <p className={`${HINT} m-0`}>{t`Printing needs a print or admin key.`}</p>}
            {outcome?.kind === "failed" && <p role="alert" className="text-bad">{errorText(outcome.error)}</p>}
          </section>

          {pagePrinter && selected && (
            <SheetSection
              items={cart.items}
              printer={selected}
              preselectedSheet={linkedSheet}
              preselectedTray={linkedTray}
              onQueued={(queued) => {
                cart.removeItems(queued);
                setSheetPrinted(true);
              }}
              onAccepted={(submitted) => {
                cart.removeItems(submitted);
                setSheetPrinted(true);
              }}
            />
          )}
        </>
      )}
    </div>
  );
}
