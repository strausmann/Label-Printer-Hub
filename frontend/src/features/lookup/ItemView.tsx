import { useLingui } from "@lingui/react/macro";
import { getRouteApi, Link } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { Button } from "react-aria-components";
import { ApiError } from "../../api/client";
import { useSession } from "../../app/session";
import { PRIMARY_BUTTON, FIELD } from "../../shell/SignIn";
import { usePrinters, usePrinterStatus, usePrinterStatuses } from "../printers/api";
import { HINT } from "../settings/controls";
import { PANEL } from "../ui";
import {
  DEFAULT_CONTENT_TYPE,
  LOOKUP_CONTENT_TYPES,
  QR_PATH_APP,
  safeHref,
  useAppName,
  useContentTypeLabel,
} from "./apps";
import { useLookup, usePreviewImage, usePrintNow, type LookupResult } from "./api";
import { MAX_COPIES, useCart, type ContentType, type LookupApp } from "./cart";
import { LayoutPicker } from "../layout/LayoutPicker";
import { tapeMmOfStatus, useLabelLayout } from "../layout/ql";
import { LabelPreview } from "./LabelPreview";
import { lookupIdFromQrPath } from "./labelUrl";
import { recordRecent } from "./recent";
import { PrinterPicker, usePrinterChoice, usePrintErrorText } from "./PrinterPicker";
import { SheetSection } from "../sheets/print/SheetSection";

const lookupRoute = getRouteApi("/lookup/$app/$id");

/** `/lookup/$app/$id` for any app; an app this build does not know reads as not found. */
export function LookupPage() {
  const { app, id } = lookupRoute.useParams();
  return <ItemRoute app={app} id={id} />;
}

const locApi = getRouteApi("/loc/$id");
const assetApi = getRouteApi("/asset/$id");
const spoolApi = getRouteApi("/spool/$id");
const productApi = getRouteApi("/product/$id");

/** The paths printed in QR codes (same mapping as `backend/app/api/routes/qr.py`). */
export const LocPage = () => <ItemRoute app={QR_PATH_APP.loc} id={lookupIdFromQrPath("loc", locApi.useParams().id)} />;
export const AssetPage = () => <ItemRoute app={QR_PATH_APP.asset} id={assetApi.useParams().id} />;
export const SpoolPage = () => <ItemRoute app={QR_PATH_APP.spool} id={spoolApi.useParams().id} />;
export const ProductPage = () => <ItemRoute app={QR_PATH_APP.product} id={productApi.useParams().id} />;

function ItemRoute({ app, id }: { app: string; id: string }) {
  const { t } = useLingui();
  if (app !== "snipeit" && app !== "grocy" && app !== "spoolman") {
    return <NotFound heading={t`Not found`} id={id} />;
  }
  return <Item app={app} id={id} />;
}

function NotFound({ heading, id }: { heading: string; id: string }) {
  const { t } = useLingui();
  return (
    <div className="flex flex-col gap-3">
      <h1 className="text-title font-bold">{heading}</h1>
      <p className="text-ink-2">
        {t`No item has this ID:`} <code className="text-ink">{id}</code>
      </p>
    </div>
  );
}

function Item({ app, id }: { app: LookupApp; id: string }) {
  const { t } = useLingui();
  const appNames = useAppName();
  const name = appNames(app);
  const lookup = useLookup(app, id);
  const found = lookup.data;
  // An item that was shown goes on the start page's "Recently opened"; a failed lookup does not.
  useEffect(() => {
    if (found) recordRecent(app, { id, name: found.name ?? id });
  }, [app, id, found]);

  if (lookup.isPending) return <p role="status" className="text-ink-2">{t`Loading…`}</p>;
  if (lookup.isError) {
    const error = lookup.error;
    if (error instanceof ApiError && error.status === 404) {
      return <NotFound heading={t`Not found in ${name}`} id={id} />;
    }
    if (error instanceof ApiError && error.status === 503 && error.code === "integration_not_configured") {
      return (
        <div className="flex flex-col gap-3">
          <h1 className="text-title font-bold">{t`This item cannot be shown`}</h1>
          <p className="text-ink-2">{t`${name} is not set up yet, so this item cannot be shown.`}</p>
          <Link to="/settings/integrations" className="w-fit text-link underline underline-offset-2">
            {t`Open Settings › Integrations`}
          </Link>
        </div>
      );
    }
    return (
      <div className="flex flex-col gap-3">
        <p role="alert">{t`The item could not be loaded.`}</p>
        <Button className="w-fit text-link underline underline-offset-2" onPress={() => void lookup.refetch()}>
          {t`Try again`}
        </Button>
      </div>
    );
  }
  return <ItemDetail item={lookup.data} />;
}

function ItemDetail({ item }: { item: LookupResult }) {
  const { t } = useLingui();
  const appNames = useAppName();
  const contentLabel = useContentTypeLabel();
  const errorText = usePrintErrorText();
  // A read key may look and fill the cart but not print: say so before the press, not with a 403 after it.
  const readOnly = useSession().scope === "read";
  const cart = useCart();
  const printers = usePrinters();
  const { usable, selected, choose } = usePrinterChoice(printers.data);
  const status = usePrinterStatus(selected?.id ?? "", !!selected);
  const statuses = usePrinterStatuses(usable);
  const [contentType, setContentType] = useState<ContentType>(DEFAULT_CONTENT_TYPE);
  const [copies, setCopies] = useState(1);
  const print = usePrintNow();
  // A page printer prints onto sheets (the sheet section); only tape printers get the tape preview.
  const pagePrinter = selected?.backend === "ipp";
  const tapeMm = tapeMmOfStatus(selected ? status.data : null);
  const layout = useLabelLayout(selected, tapeMm);
  const preview = usePreviewImage(item, contentType, tapeMm, !printers.isPending && !pagePrinter && !(selected && status.isPending), layout.options);

  const appName = appNames(item.app);
  const printerName = selected?.name ?? "";
  const href = safeHref(item.url);
  const title = item.name ?? item.id;
  const inCart = cart.items.length;
  const asItem = { app: item.app, id: item.id, name: title, content_type: contentType, copies };

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 flex-col gap-2">
          <h1 className="break-words text-title font-bold">{title}</h1>
          <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-ink-2">
            <span>{appName}</span>
            <code className="text-ink">{item.id}</code>
            {href && (
              <a href={href} target="_blank" rel="noopener noreferrer" className="text-link underline underline-offset-2">
                {t`Open in ${appName}`}
              </a>
            )}
          </p>
        </div>
        {inCart > 0 && (
          <Link to="/cart" className="press inline-flex h-11 items-center text-link underline underline-offset-2">
            {t`Cart (${inCart})`}
          </Link>
        )}
      </header>

      <div className={pagePrinter ? "grid gap-4 lg:grid-cols-[22rem_minmax(0,1fr)]" : "grid gap-4 lg:grid-cols-[minmax(0,1fr)_22rem]"}>
        {!pagePrinter && (
        <section aria-labelledby="preview-h" className={`${PANEL} flex flex-col gap-3`}>
          <h2 id="preview-h" className="text-section font-bold">{t`Preview`}</h2>
          <LabelPreview preview={preview} layout={layout.options} />
        </section>
        )}

        <section aria-labelledby="print-h" className={`${PANEL} flex flex-col gap-4`}>
          <h2 id="print-h" className="text-section font-bold">{t`Print`}</h2>
          <PrinterPicker
            printers={usable}
            value={selected?.id ?? null}
            onChange={choose}
            loading={printers.isPending}
            statuses={statuses}
          />
          <label className="flex flex-col gap-1.5">
            <span className="font-bold">{t`Layout`}</span>
            <select className={FIELD} value={contentType} onChange={(e) => setContentType(e.target.value as ContentType)}>
              {LOOKUP_CONTENT_TYPES.map((c) => (
                <option key={c} value={c}>
                  {contentLabel(c)}
                </option>
              ))}
            </select>
          </label>
          {layout.active && (
            <LayoutPicker
              orientation={layout.choice.orientation}
              preset={layout.choice.preset}
              onOrientation={layout.setOrientation}
              onPreset={layout.setPreset}
            />
          )}
          <label className="flex flex-col gap-1.5">
            <span className="font-bold">{t`Copies`}</span>
            <input
              type="number"
              inputMode="numeric"
              min={1}
              max={MAX_COPIES}
              value={copies}
              className={`${FIELD} code`}
              onChange={(e) => setCopies(Math.min(MAX_COPIES, Math.max(1, Math.round(Number(e.target.value)) || 1)))}
            />
          </label>
          <div className="flex flex-wrap gap-2">
            {/* A page printer prints through the sheet section; "Print now" is the tape printers' one-label batch. */}
            {!pagePrinter && (
              <Button
                className={PRIMARY_BUTTON}
                isDisabled={!selected || print.isPending || readOnly}
                onPress={() => selected && print.mutate({ printerKey: selected.id, item: asItem, layout: layout.options })}
              >
                {t`Print now`}
              </Button>
            )}
            <Button
              className="press inline-flex h-11 items-center justify-center rounded-r2 border border-line-strong bg-surface px-4 text-small font-bold text-ink hover:bg-sunken data-[focus-visible]:outline-3 data-[focus-visible]:outline-offset-2 data-[focus-visible]:outline-link"
              onPress={() => cart.add(asItem)}
            >
              {t`Add to cart`}
            </Button>
          </div>
          {readOnly && !pagePrinter && <p className={`${HINT} m-0`}>{t`Printing needs a print or admin key.`}</p>}
          {print.isError && (
            <p role="alert" className="text-bad">{errorText(print.error)}</p>
          )}
          {print.isSuccess && selected && (
            <p role="status">
              {t`Sent to ${printerName}.`}{" "}
              {print.data.job_ids[0] && (
                <Link to="/jobs/$jobId" params={{ jobId: print.data.job_ids[0] }} className="text-link underline underline-offset-2">
                  {t`View the job`}
                </Link>
              )}
            </p>
          )}
        </section>

        {pagePrinter && selected && <SheetSection items={[asItem]} printer={selected} />}
      </div>
    </div>
  );
}
