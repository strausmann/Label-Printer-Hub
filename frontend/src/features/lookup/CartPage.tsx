import { plural } from "@lingui/core/macro";
import { useLingui } from "@lingui/react/macro";
import { getRouteApi, Link } from "@tanstack/react-router";
import { useState } from "react";
import { Button } from "react-aria-components";
import { FIELD, PRIMARY_BUTTON } from "../../shell/SignIn";
import { usePrinters, usePrinterStatuses } from "../printers/api";
import { PANEL, SECONDARY_BUTTON } from "../ui";
import { useAppName } from "./apps";
import { BatchStatusError, MAX_COPIES, useCart, type BatchRead } from "./cart";
import { PrinterPicker, usePrinterChoice, usePrintErrorText } from "./PrinterPicker";
import { SheetSection } from "../sheets/print/SheetSection";

const cartApi = getRouteApi("/cart");

type Outcome = { kind: "sent"; labels: number; printer: string; batch: BatchRead | null } | { kind: "failed"; error: unknown };

/** The cart: everything collected from item views, printed as ONE batch (ADR 0013). */
export function CartPage() {
  const { t } = useLingui();
  const appName = useAppName();
  const errorText = usePrintErrorText();
  const cart = useCart();
  const printers = usePrinters();
  const { usable, selected, choose } = usePrinterChoice(printers.data);
  const statuses = usePrinterStatuses(usable);
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  // `/cart?sheet=<code>` (the link from a sheet's page) preselects that sheet in the sheet section.
  const { sheet: linkedSheet } = cartApi.useSearch();
  // The cart empties when the hub accepts a sheet print; the section stays to show where the labels went.
  const [sheetPrinted, setSheetPrinted] = useState(false);
  const pagePrinter = selected?.backend === "ipp";
  const labels = cart.items.reduce((sum, i) => sum + i.copies, 0);

  const send = async () => {
    if (!selected) return;
    const count = labels;
    setBusy(true);
    try {
      const batch = await cart.print(selected.id);
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

      {cart.items.length === 0 && !sheetPrinted && (
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
            <div className="flex flex-wrap gap-2">
              {/* A page printer prints through the sheet section below. */}
              {!pagePrinter && (
                <Button className={PRIMARY_BUTTON} isDisabled={!selected || busy} onPress={() => void send()}>
                  {plural(labels, { one: "Print # label", other: "Print # labels" })}
                </Button>
              )}
              {cart.items.length > 0 && (
                <Button className={SECONDARY_BUTTON} isDisabled={busy} onPress={cart.clear}>
                  {t`Empty the cart`}
                </Button>
              )}
            </div>
            {outcome?.kind === "failed" && <p role="alert" className="text-bad">{errorText(outcome.error)}</p>}
          </section>

          {pagePrinter && selected && (
            <SheetSection
              items={cart.items}
              printer={selected}
              preselectedSheet={linkedSheet}
              onQueued={(queued) => cart.removeItems(queued)}
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
