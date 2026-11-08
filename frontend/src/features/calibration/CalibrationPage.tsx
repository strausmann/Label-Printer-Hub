import { useLingui } from "@lingui/react/macro";
import { getRouteApi, Link, useNavigate } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import { Button } from "react-aria-components";
import { useSession } from "../../app/session";
import { PRIMARY_BUTTON } from "../../shell/SignIn";
import { useSheetTypes, type SheetTypeRead } from "../archive/api";
import { usePrinters, usePrinterStatus, type Printer } from "../printers/api";
import { PrinterRow } from "../sheets/print/PrinterRow";
import { HINT, SelectField, TextInput } from "../settings/controls";
import { formatMm } from "../sheets/cellState";
import { typeLabelWithKey } from "../sheets/typeLabel";
import { PANEL, SECONDARY_BUTTON, SECTION_HEADING } from "../ui";
import {
  calibrationPdfUrl,
  useCalibration,
  useCapabilities,
  usePrintCalibrationPage,
  useResetCalibration,
  useSaveCalibration,
  type CalibrationRead,
} from "./api";
import { CalibrationSchematic, GapCrossing } from "./CalibrationSchematic";
import { useCalibrationErrorText, useValueNames } from "./errors";
import { parseNumber, usableTypes } from "./model";
import { ReadingsHelper } from "./ReadingsHelper";

const calibrationApi = getRouteApi("/calibration");

type MeasuredOn = { type_key: string; version: number };

const FIELDS = ["offset_x_mm", "offset_y_mm", "scale_x", "scale_y", "rotation_deg"] as const;
type Field = (typeof FIELDS)[number];
type Draft = Record<Field, string>;

const IDENTITY: Record<Field, number> = { offset_x_mm: 0, offset_y_mm: 0, scale_x: 1, scale_y: 1, rotation_deg: 0 };

const hasValues = (row: CalibrationRead | undefined): boolean => !!row && FIELDS.some((f) => row[f] != null);

/** A length without its unit, for "45.7 × 21.2 mm". */
const plainMm = (v: number, locale: string) => new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }).format(Math.round(v * 100) / 100);

function useNumberText(): (n: number) => string {
  const { i18n } = useLingui();
  return (n) => new Intl.NumberFormat(i18n.locale, { maximumFractionDigits: 6, useGrouping: false }).format(n);
}

function draftOf(row: CalibrationRead | undefined, text: (n: number) => string): Draft {
  const d = {} as Draft;
  for (const f of FIELDS) d[f] = text(row?.[f] ?? IDENTITY[f]);
  return d;
}

export function CalibrationPage() {
  const { t } = useLingui();
  const search = calibrationApi.useSearch();
  const navigate = useNavigate();
  const printers = usePrinters();
  const pagePrinters = useMemo(() => (printers.data ?? []).filter((p) => p.backend === "ipp" && p.enabled), [printers.data]);
  const printer = pagePrinters.find((p) => p.id === search.printer) ?? pagePrinters[0];
  const calibration = useCalibration(printer?.id ?? "");
  const capabilities = useCapabilities(printer?.id ?? "");
  const trays = useMemo(() => {
    const labels = new Map((capabilities.data?.trays ?? []).map((x) => [x.key, x.label]));
    return (calibration.data ?? []).map((row) => ({ key: row.tray, label: labels.get(row.tray) ?? row.tray }));
  }, [calibration.data, capabilities.data]);
  const defaultTray = capabilities.data?.trays?.find((x) => x.is_default && trays.some((y) => y.key === x.key))?.key ?? trays[0]?.key;
  const tray = trays.find((x) => x.key === search.tray)?.key ?? defaultTray;

  // The address always names what the page shows, so a copied link opens the same tray.
  useEffect(() => {
    if (!printer || (calibration.isSuccess && !tray)) return;
    if (search.printer !== printer.id || (tray && search.tray !== tray)) {
      void navigate({ to: "/calibration", search: { printer: printer.id, tray }, replace: true });
    }
  }, [printer, tray, calibration.isSuccess, search.printer, search.tray, navigate]);

  const choosePrinter = (id: string) => void navigate({ to: "/calibration", search: { printer: id, tray: undefined }, replace: true });
  const chooseTray = (key: string) => void navigate({ to: "/calibration", search: { printer: printer?.id, tray: key }, replace: true });

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-title font-bold">{t`Calibration`}</h1>
        <p className={`${HINT} mt-1 max-w-prose`}>
          {t`A printer rarely prints exactly where the page says. Measure how far it is off on a real sheet, and the hub moves every print by the opposite.`}
        </p>
      </div>

      {printers.isPending ? (
        <p role="status" className="text-ink-2">{t`Loading…`}</p>
      ) : printers.isError ? (
        <p role="alert" className="text-bad">{t`The printers could not be loaded.`}</p>
      ) : !printer ? (
        <p className={PANEL}>{t`There is no page printer yet. Add one under Settings › Printers.`}</p>
      ) : (
        <>
          <section aria-labelledby="cal-printer-h" className={`${PANEL} flex flex-col gap-4`}>
            <h2 id="cal-printer-h" className={SECTION_HEADING}>{t`Printer and tray`}</h2>
            <div className="grid gap-4 sm:grid-cols-2">
              <SelectField label={t`Printer`} value={printer.id} options={pagePrinters.map((p) => ({ id: p.id, label: p.name }))} onChange={choosePrinter} />
              {trays.length > 1 && tray ? (
                <SelectField label={t`Tray`} value={tray} options={trays.map((x) => ({ id: x.key, label: x.label }))} onChange={chooseTray} />
              ) : (
                <p className={`${HINT} self-end`}>{calibration.isPending ? t`Loading…` : trays[0] ? trays[0].label : t`This printer has no tray to calibrate.`}</p>
              )}
            </div>
            <PrinterState printer={printer} />
          </section>

          {calibration.isPending ? (
            <p role="status" className="text-ink-2">{t`Loading…`}</p>
          ) : calibration.isError ? (
            <p role="alert" className="text-bad">{t`The calibration could not be loaded.`}</p>
          ) : tray ? (
            <Workbench
              key={`${printer.id}/${tray}`}
              printer={printer}
              tray={tray}
              trayLabel={trays.find((x) => x.key === tray)?.label ?? tray}
              stored={calibration.data.find((r) => r.tray === tray)}
            />
          ) : null}
        </>
      )}
    </div>
  );
}

function PrinterState({ printer }: { printer: Printer }) {
  const status = usePrinterStatus(printer.id);
  return <PrinterRow printer={printer} status={status.data} />;
}

interface WorkbenchProps {
  printer: Printer;
  tray: string;
  trayLabel: string;
  stored: CalibrationRead | undefined;
}

/** Everything for one printer and tray; it is rebuilt when either changes. */
function Workbench({ printer, tray, trayLabel, stored }: WorkbenchProps) {
  const { t, i18n } = useLingui();
  const session = useSession();
  const canPrint = session.scope === "print" || session.scope === "admin";
  const admin = session.scope === "admin";
  const types = useSheetTypes();
  const usable = useMemo(() => usableTypes(types.data ?? []), [types.data]);
  const [typeChoice, setTypeChoice] = useState<string | null>(null);
  const type: SheetTypeRead | undefined = usable.find((x) => x.key === typeChoice) ?? usable[0];

  // The values of step 2 live here: the form edits them and the readings helper fills them.
  const text = useNumberText();
  const key = stored?.updated_at ?? "none";
  // `fit` is the type and version of the readings the values came from; null for values typed by hand.
  const [draft, setDraft] = useState<{ key: string; fields: Draft; fit: MeasuredOn | null }>(() => ({ key, fields: draftOf(stored, text), fit: null }));
  // The stored values changed (a save, a reset, another tab): the form follows them.
  if (draft.key !== key) setDraft({ key, fields: draftOf(stored, text), fit: null });
  // A fit result is saved as measured on the type it was fitted on; typed values on the type chosen now.
  const measuredOn: MeasuredOn | null = draft.fit ?? (type ? { type_key: type.key, version: type.current_version } : null);

  return (
    <>
      <CurrentValues stored={stored} />

      <section aria-labelledby="cal-step1-h" className={`${PANEL} flex flex-col gap-4`}>
        <h2 id="cal-step1-h" className={SECTION_HEADING}>{t`Step 1: Print the calibration page`}</h2>
        <p className={`${HINT} max-w-prose`}>
          {t`Print it onto a real sheet of labels (the sheet is used up). The page is always printed without correction, so what you measure is the printer's own deviation.`}
        </p>
        {types.isPending ? (
          <p role="status" className="text-ink-2">{t`Loading…`}</p>
        ) : !type ? (
          <p className="text-ink-2">{t`There is no sheet type with at least two columns and two rows.`}</p>
        ) : (
          <>
            <SelectField
              label={t`Sheet type`}
              value={type.key}
              options={usable.map((x) => ({ id: x.key, label: `${typeLabelWithKey(x)} · ${plainMm(x.geometry.label_w, i18n.locale)} × ${formatMm(x.geometry.label_h, i18n.locale)}` }))}
              onChange={setTypeChoice}
            />
            <CalibrationSchematic geometry={type.geometry} typeName={typeLabelWithKey(type)} />
            <GapCrossing colGap={Math.min(2, type.geometry.cols - 1)} rowGap={Math.min(6, type.geometry.rows - 1)} />
            <div className="flex flex-wrap items-center gap-3">
              <PrintAction
                key={`print/${type.key}`}
                printerId={printer.id}
                tray={tray}
                type={type}
                corrected={false}
                disabled={!canPrint}
                label={t`Print calibration page`}
                done={t`The calibration page is queued.`}
                primary
                noKey={!canPrint}
              />
              <a
                href={calibrationPdfUrl(printer.id, tray, { type: type.key, version: type.current_version, corrected: false })}
                download
                className={SECONDARY_BUTTON}
              >
                {t`Download PDF`}
              </a>
            </div>
          </>
        )}
      </section>

      <section aria-labelledby="cal-step2-h" className={`${PANEL} flex flex-col gap-5`}>
        <h2 id="cal-step2-h" className={SECTION_HEADING}>{t`Step 2: Enter the deviation`}</h2>
        {type && (
          <div className="flex flex-col gap-3">
            <h3 className="m-0 text-body font-bold">{t`Measure with the readings helper`}</h3>
            <ReadingsHelper
              key={type.key}
              printerId={printer.id}
              tray={tray}
              typeKey={type.key}
              version={type.current_version}
              cols={type.geometry.cols}
              rows={type.geometry.rows}
              onFitted={(values, fit) => setDraft({ key, fields: draftOfValues(values, text), fit })}
            />
          </div>
        )}
        <h3 className="m-0 text-body font-bold">{t`Or enter the values directly`}</h3>
        <ValuesForm
          printer={printer}
          tray={tray}
          trayLabel={trayLabel}
          hasStored={hasValues(stored)}
          fields={draft.fields}
          onChange={(fields) => setDraft({ key, fields, fit: null })}
          measuredOn={measuredOn}
          admin={admin}
        />
      </section>

      <section aria-labelledby="cal-step3-h" className={`${PANEL} flex flex-col gap-4`}>
        <h2 id="cal-step3-h" className={SECTION_HEADING}>{t`Step 3: Check the result`}</h2>
        <p className={`${HINT} max-w-prose`}>
          {t`Print the same page again, now with the correction. Every crossing should then be within 0.5 mm. If not, measure again and adjust.`}
        </p>
        {type && (
          <div className="flex flex-wrap items-center gap-3">
            <PrintAction
              key={`check/${type.key}`}
              printerId={printer.id}
              tray={tray}
              type={type}
              corrected
              disabled={!canPrint || !hasValues(stored)}
              noKey={!canPrint}
              label={t`Check print with correction`}
              done={t`The check page is queued.`}
            />
            {!hasValues(stored) && <span className={HINT}>{t`Save a correction first.`}</span>}
          </div>
        )}
      </section>
    </>
  );
}

function CurrentValues({ stored }: { stored: CalibrationRead | undefined }) {
  const { t, i18n } = useLingui();
  const text = useNumberText();
  const names = useValueNames();
  const has = hasValues(stored);
  const changed = stored?.updated_at ? new Date(stored.updated_at) : null;
  const value = (f: Field) => {
    const n = stored?.[f] ?? IDENTITY[f];
    return f.startsWith("offset") ? `${text(n)} mm` : f === "rotation_deg" ? `${text(n)}°` : text(n);
  };
  return (
    <section aria-labelledby="cal-current-h" className={PANEL}>
      <h2 id="cal-current-h" className={SECTION_HEADING}>{t`Current values`}</h2>
      {has ? (
        <>
          <dl className="m-0 mt-3 grid grid-cols-[auto_1fr] gap-x-6 gap-y-1 text-small sm:grid-cols-[repeat(5,auto)] sm:gap-y-0">
            {FIELDS.map((f) => (
              <div key={f} className="contents sm:flex sm:flex-col">
                <dt className="text-ink-2">{names[f]}</dt>
                <dd className="m-0 font-bold tabular-nums">{value(f)}</dd>
              </div>
            ))}
          </dl>
          {changed && !Number.isNaN(changed.getTime()) && (
            <p className={`${HINT} mt-3`}>
              {t`Last changed`}{" "}
              <time dateTime={stored!.updated_at!}>{changed.toLocaleString(i18n.locale, { dateStyle: "medium", timeStyle: "short" })}</time>
            </p>
          )}
        </>
      ) : (
        <p className={`${HINT} mt-2`}>{t`No correction stored for this tray.`}</p>
      )}
    </section>
  );
}

interface PrintActionProps {
  printerId: string;
  tray: string;
  type: SheetTypeRead;
  corrected: boolean;
  disabled: boolean;
  label: string;
  done: string;
  primary?: boolean;
  noKey: boolean;
}

function PrintAction({ printerId, tray, type, corrected, disabled, label, done, primary, noKey }: PrintActionProps) {
  const { t } = useLingui();
  const errorText = useCalibrationErrorText();
  const print = usePrintCalibrationPage(printerId);
  return (
    <div className="flex min-w-0 flex-col gap-2">
      <Button
        isDisabled={disabled || print.isPending}
        onPress={() => print.mutate({ tray, request: { type: type.key, version: type.current_version, corrected } })}
        className={primary ? PRIMARY_BUTTON : SECONDARY_BUTTON}
      >
        {label}
      </Button>
      {noKey && <p className={`${HINT} m-0`}>{t`Printing needs a print or admin key.`}</p>}
      {print.isError && (
        <p role="alert" className="m-0 text-bad">
          {errorText(print.error, t`The page could not be queued.`)}
        </p>
      )}
      {print.isSuccess && (
        <p role="status" className="m-0 text-ok">
          {done}{" "}
          <Link to="/jobs/$jobId" params={{ jobId: print.data.job_id }} className="text-link underline underline-offset-2">
            {t`Show the job`}
          </Link>
        </p>
      )}
    </div>
  );
}

interface ValuesFormProps {
  printer: Printer;
  tray: string;
  trayLabel: string;
  hasStored: boolean;
  fields: Draft;
  onChange: (fields: Draft) => void;
  measuredOn: MeasuredOn | null;
  admin: boolean;
}

function ValuesForm({ printer, tray, trayLabel, hasStored, fields, onChange, measuredOn, admin }: ValuesFormProps) {
  const { t } = useLingui();
  const names = useValueNames();
  const errorText = useCalibrationErrorText();
  const save = useSaveCalibration(printer.id);
  const reset = useResetCalibration(printer.id);
  const [invalid, setInvalid] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [message, setMessage] = useState<"saved" | "reset" | null>(null);
  const setField = (f: Field, v: string) => {
    onChange({ ...fields, [f]: v });
    setInvalid(null);
    setMessage(null);
  };

  const submit = () => {
    const parsed = {} as Record<Field, number>;
    for (const f of FIELDS) {
      const n = parseNumber(fields[f]);
      if (n === null) {
        const name = names[f]!;
        setInvalid(t`${name} is not a number.`);
        return;
      }
      parsed[f] = n;
    }
    setInvalid(null);
    setMessage(null);
    save.mutate(
      { tray, values: { ...parsed, ...(measuredOn ? { measured_on: measuredOn } : {}) } },
      { onSuccess: () => setMessage("saved") },
    );
  };
  const doReset = () => {
    setConfirming(false);
    setMessage(null);
    reset.mutate({ tray }, { onSuccess: () => setMessage("reset") });
  };

  const number = (f: Field, label: string, description: string) => (
    <TextInput label={label} value={fields[f]} onChange={(v) => setField(f, v)} inputMode="decimal" mono description={description} />
  );
  const printerName = printer.name;

  return (
    <div className="flex flex-col gap-4">
      <p className={`${HINT} max-w-prose`}>
        {t`Enter what the printer did wrong; the hub applies the opposite itself.`}
      </p>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {number("offset_x_mm", t`Offset X (mm)`, t`+ = printed too far right`)}
        {number("offset_y_mm", t`Offset Y (mm)`, t`+ = printed too low`)}
        {number("scale_x", t`Scale X`, t`above 1 = printed too large`)}
        {number("scale_y", t`Scale Y`, t`above 1 = printed too large`)}
        {number("rotation_deg", t`Rotation (°)`, t`+ = rotated clockwise`)}
      </div>

      {invalid && <p role="alert" className="m-0 text-bad">{invalid}</p>}
      {save.isError && <p role="alert" className="m-0 text-bad">{errorText(save.error, t`The correction could not be saved.`)}</p>}
      {reset.isError && <p role="alert" className="m-0 text-bad">{errorText(reset.error, t`The correction could not be reset.`)}</p>}
      {message === "saved" && save.isSuccess && <p role="status" className="m-0 text-ok">{t`Saved. New prints use this correction.`}</p>}
      {message === "reset" && reset.isSuccess && <p role="status" className="m-0 text-ok">{t`Reset. This tray prints without correction.`}</p>}

      <div className="flex flex-wrap items-center gap-3">
        <Button isDisabled={!admin || save.isPending} onPress={submit} className={PRIMARY_BUTTON}>
          {t`Save for this printer and tray`}
        </Button>
        {admin && hasStored && !confirming && (
          <Button isDisabled={reset.isPending} onPress={() => setConfirming(true)} className={SECONDARY_BUTTON}>
            {t`Reset to no correction`}
          </Button>
        )}
      </div>
      {!admin && <p className={HINT}>{t`Saving needs an admin key, because it changes every print on this tray.`}</p>}
      {confirming && (
        <div role="group" aria-label={t`Confirm the reset`} className="flex flex-col gap-3 rounded-r2 border border-warn bg-sunken p-3">
          <p className="m-0">{t`Remove the correction of ${trayLabel} on ${printerName}? Prints on this tray are then not corrected.`}</p>
          <div className="flex flex-wrap gap-3">
            <Button onPress={doReset} className={PRIMARY_BUTTON}>{t`Yes, reset`}</Button>
            <Button onPress={() => setConfirming(false)} className={SECONDARY_BUTTON}>{t`Cancel`}</Button>
          </div>
        </div>
      )}
    </div>
  );
}

function draftOfValues(values: Record<Field, number>, text: (n: number) => string): Draft {
  const d = {} as Draft;
  for (const f of FIELDS) d[f] = text(values[f]);
  return d;
}
