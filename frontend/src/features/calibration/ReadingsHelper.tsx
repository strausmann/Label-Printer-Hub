import { useLingui } from "@lingui/react/macro";
import { useRef, useState } from "react";
import { Button } from "react-aria-components";
import { PRIMARY_BUTTON } from "../../shell/SignIn";
import { HINT, SelectField, TextInput } from "../settings/controls";
import { SECONDARY_BUTTON } from "../ui";
import { useFit, type FitResponse } from "./api";
import { useCalibrationErrorText, useRangeWords } from "./errors";
import {
  canFit,
  completeReadings,
  crossingName,
  emptyReading,
  readingsRequest,
  suggestedCrossings,
  type ReadingRow,
} from "./model";

const MAX_ROWS = 200;

/** The first crossing, counting across then down, that no row names yet; S1 · Z1 when all are taken. */
function unusedCrossing(list: readonly ReadingRow[], cols: number, rows: number) {
  for (let z = 1; z < rows; z++) {
    for (let s = 1; s < cols; s++) {
      if (!list.some((r) => r.col_gap === s && r.row_gap === z)) return { col_gap: s, row_gap: z };
    }
  }
  return { col_gap: 1, row_gap: 1 };
}

interface Fitted {
  response: FitResponse;
  /** The crossings that were sent, in order, so the table can name them. */
  crossings: { col_gap: number; row_gap: number; across_mm: number; down_mm: number }[];
}

export interface ReadingsHelperProps {
  printerId: string;
  tray: string;
  typeKey: string;
  version: number;
  cols: number;
  rows: number;
  /** Called with the fitted values and the type and version they were measured on, when they are inside the allowed ranges. */
  onFitted: (values: FitResponse["values"], measuredOn: { type_key: string; version: number }) => void;
}

/**
 * The readings helper: the person reads the deviation at named crossings, the server fits the
 * five values. Nothing is stored here; the values land in the form below for the person to save.
 */
export function ReadingsHelper({ printerId, tray, typeKey, version, cols, rows, onFitted }: ReadingsHelperProps) {
  const { t, i18n } = useLingui();
  const errorText = useCalibrationErrorText();
  const rangeWords = useRangeWords();
  const fit = useFit(printerId);
  const initial = useState(() => suggestedCrossings(cols, rows).map((c, i) => emptyReading(i, c)))[0];
  // Row ids come from one counter that only counts up: a removed row's id is never handed out again.
  const nextId = useRef(initial.length);
  const [list, setList] = useState<ReadingRow[]>(initial);
  const [fitted, setFitted] = useState<Fitted | null>(null);
  const [filled, setFilled] = useState(false);
  const ready = canFit(list);
  const gapOptions = (n: number) => Array.from({ length: n }, (_, i) => ({ id: String(i + 1), label: String(i + 1) }));
  const mm = (v: number) => `${new Intl.NumberFormat(i18n.locale, { maximumFractionDigits: 2, useGrouping: false }).format(v)} mm`;

  const edit = (id: number, patch: Partial<ReadingRow>) => {
    setList((rowsNow) => rowsNow.map((r) => (r.id === id ? { ...r, ...patch } : r)));
    setFitted(null);
    setFilled(false);
    fit.reset();
  };
  const add = () => {
    const id = nextId.current++;
    setList((rowsNow) => [...rowsNow, emptyReading(id, unusedCrossing(rowsNow, cols, rows))]);
  };
  const remove = (id: number) => {
    setList((rowsNow) => rowsNow.filter((r) => r.id !== id));
    setFitted(null);
    setFilled(false);
    fit.reset();
  };

  const run = () => {
    const request = readingsRequest(typeKey, version, list);
    setFilled(false);
    fit.mutate(
      { tray, request },
      {
        onSuccess: (response) => {
          setFitted({ response, crossings: request.readings });
          if (response.out_of_range.length === 0) {
            onFitted(response.values, { type_key: typeKey, version });
            setFilled(true);
          }
        },
      },
    );
  };

  // The server numbers the complete readings it got; the person sees rows, empty ones included.
  const completeRows = list.flatMap((r, i) => (completeReadings([r]).length === 1 ? [i + 1] : []));
  const outOfRange = fitted?.response.out_of_range ?? [];
  const outOfRangeList = outOfRange.map((name) => rangeWords[name] ?? name).join(", ");

  // With two columns (or two rows) every crossing lies on one line: nothing to fit.
  if (cols <= 2 || rows <= 2) {
    return <p className={HINT}>{t`On this sheet all crossings lie on one line, so the readings cannot be fitted. Enter the values directly.`}</p>;
  }

  return (
    <div className="flex flex-col gap-4">
      <p className={HINT}>
        {t`Read the deviation at three or more crossings that are far apart, in both directions. + across = the ink lies to the right, + down = the ink lies below.`}
      </p>
      <div className="flex flex-col gap-3">
        {list.map((r, index) => {
          const n = index + 1;
          const name = crossingName(r.col_gap, r.row_gap);
          return (
            <fieldset key={r.id} aria-label={t`Reading ${n}`} className="m-0 grid grid-cols-2 gap-3 rounded-r2 bg-sunken p-3 sm:grid-cols-[5rem_5rem_1fr_1fr_auto] sm:items-end">
              <SelectField label={t`Gap S`} value={String(r.col_gap)} options={gapOptions(Math.max(cols - 1, 1))} onChange={(id) => edit(r.id, { col_gap: Number(id) })} />
              <SelectField label={t`Gap Z`} value={String(r.row_gap)} options={gapOptions(Math.max(rows - 1, 1))} onChange={(id) => edit(r.id, { row_gap: Number(id) })} />
              <TextInput label={t`Across at ${name} (mm)`} value={r.across} onChange={(v) => edit(r.id, { across: v })} inputMode="decimal" mono />
              <TextInput label={t`Down at ${name} (mm)`} value={r.down} onChange={(v) => edit(r.id, { down: v })} inputMode="decimal" mono />
              <Button aria-label={t`Remove reading ${n}`} onPress={() => remove(r.id)} className={`${SECONDARY_BUTTON} col-span-2 sm:col-span-1`}>
                {t`Remove`}
              </Button>
            </fieldset>
          );
        })}
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Button onPress={add} isDisabled={list.length >= MAX_ROWS} className={SECONDARY_BUTTON}>
          {t`Add reading`}
        </Button>
        <Button onPress={run} isDisabled={!ready || fit.isPending} className={PRIMARY_BUTTON}>
          {t`Fit`}
        </Button>
        {!ready && <span className={HINT}>{t`Enter at least three readings to fit.`}</span>}
      </div>

      {fit.isError && (
        <p role="alert" className="m-0 text-bad">
          {errorText(fit.error, t`The fit failed.`, completeRows)}
        </p>
      )}
      {outOfRange.length > 0 && (
        <p role="alert" className="m-0 text-bad">
          {t`These fitted values are outside the allowed range: ${outOfRangeList}. They are not filled in. More than that is a fault of the printer, not something to correct.`}
        </p>
      )}
      {filled && (
        <p role="status" className="m-0 text-ok">
          {t`The values are filled in below. Nothing is saved yet.`}
        </p>
      )}
      {fitted && (
        <div className="overflow-x-auto">
          <table aria-label={t`Result of the fit`} className="w-full border-collapse text-left text-small">
            <thead>
              <tr className="text-ink-2">
                <th scope="col" className="py-1 pr-3 font-bold">{t`Crossing`}</th>
                <th scope="col" className="py-1 pr-3 font-bold">{t`Across`}</th>
                <th scope="col" className="py-1 pr-3 font-bold">{t`Down`}</th>
                <th scope="col" className="py-1 font-bold">{t`Left over after the fit`}</th>
              </tr>
            </thead>
            <tbody>
              {fitted.crossings.map((c, i) => {
                const residual = fitted.response.residuals_mm[i] ?? 0;
                const flagged = fitted.response.flagged.includes(i);
                return (
                  <tr key={i} className="border-t border-line align-top">
                    <th scope="row" className="py-2 pr-3 font-bold tabular-nums">{crossingName(c.col_gap, c.row_gap)}</th>
                    <td className="py-2 pr-3 tabular-nums">{mm(c.across_mm)}</td>
                    <td className="py-2 pr-3 tabular-nums">{mm(c.down_mm)}</td>
                    {/* The flag sits with the value it is about: a column of its own was past the edge at 360 px. */}
                    <td className="py-2 font-bold tabular-nums">
                      {mm(residual)}
                      {flagged && <span className="block font-bold text-warn">{t`check this reading`}</span>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
