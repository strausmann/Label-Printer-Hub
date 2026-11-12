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
import { useAppName } from "./apps";
import { useLookup, usePreviewImage, type LookupResult } from "./api";
import { BatchStatusError, MAX_COPIES, useCart, type BatchRead, type CartItem, type ContentType } from "./cart";
import { LabelPreview } from "./LabelPreview";
import { PrinterPicker, usePrinterChoice, usePrintErrorText } from "./PrinterPicker";
import { SheetSection } from "../sheets/print/SheetSection";

const cartApi = getRouteApi("/cart");

/** The first item of the cart as the layout will print it: every label of the batch shares the choice. */
function CartPreview({ first, tapeMm, layout }: { first: CartItem; tapeMm: number; layout: LayoutOptions | undefined }) {
  const { t } = useLingui();
  const lookup = useLookup(first.app, first.id);
  const name = first.name;
  return (
    <section aria-label={t`Preview of ${name}`} className="flex flex-col gap-2">
      <h3 className="font-bold">{t`Preview`}</h3>
      {lookup.data ? (
        <CartPreviewImage item={lookup.data} contentType={first.content_type} tapeMm={tapeMm} layout={layout} />
      ) : (
        <p role={lookup.isError ? undefined : "status"} className="text-ink-2">
          {lookup.isError ? t`No preview available.` : t`Drawing the label…`}
        </p>
      )}
      <p className="text-small text-ink-2">{t`Shows the first item: ${name}.`}</p>
    </section>
  );
}

function CartPreviewImage({ item, contentType, tapeMm, layout }: { item: LookupResult; contentType: ContentType; tapeMm: number; layout: LayoutOptions | undefined }) {
  return <LabelPreview preview={usePreviewImage(item, contentType, tapeMm, true, layout)} layout={layout} />;
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
  const { sheet: linkedSheet } = cartApi.useSearch();
  // The cart empties when the hub accepts a sheet print, or queues all of it before a partial failure; the section
  // stays to show where the labels went (the result, or the partial-result note with the links to the queued jobs).
  const [sheetPrinted, setSheetPrinted] = useState(false);
  const pagePrinter = selected?.backend === "ipp";
  const status = usePrinterStatus(selected?.id ?? "", !!selected && !pagePrinter);
  const tapeMm = tapeMmOfStatus(selected ? status.data : null);
  const layout = useLabelLayout(selected, tapeMm);
  const labels = cart.items.reduce((sum, i) => sum + i.copies, 0);

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
              return (
              <li key={`${item.app}:${item.id}`} className="grid gap-3 rounded-r3 border border-line bg-surface p-4 sm:grid-cols-[minmax(0,1fr)_auto_auto] sm:items-center">
                <span className="flex min-w-0 flex-col">
                  <Link
                    to="/lookup/$app/$id"
                    params={{ app: item.app, id: item.id }}
                    className="truncate font-bold text-link underline underline-offset-2"
                  >
                    {item.name}
                  </Link>
                  <span className="text-small text-ink-2">
                    {appName(item.app)} · <code className="text-ink">{item.id}</code>
                  </span>
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
                <LayoutPicker
                  orientation={layout.choice.orientation}
                  preset={layout.choice.preset}
                  onOrientation={layout.setOrientation}
                  onPreset={layout.setPreset}
                />
                {cart.items[0] && <CartPreview first={cart.items[0]} tapeMm={tapeMm} layout={layout.options} />}
              </>
            )}
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
