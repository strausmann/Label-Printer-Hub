import { useEffect, useState } from "react";
import type { components } from "../../api/schema.gen";
import { tapeMmOf } from "../lookup/apps";
import type { Printer, PrinterStatus } from "../printers/api";

export type Orientation = components["schemas"]["LabelOrientation"];
export type Preset = components["schemas"]["QlLayoutPreset"];
type StoredDefaults = Record<string, components["schemas"]["LayoutDefault"]> | undefined;

/** The tape the QL layouts exist for: across and the presets are 62 mm only. */
export const QL_WIDE_MM = 62;
export const PRESETS: readonly Preset[] = ["compact", "small_qr", "standard"];

/** What a 62 mm QL tape prints with when nothing is stored (the backend's tape default). */
export const TAPE_DEFAULT = { orientation: "across", preset: "compact" } as const satisfies { orientation: Orientation; preset: Preset };

export interface LayoutChoice {
  orientation: Orientation;
  preset: Preset;
}

/** The fields a print or preview request takes; the preset is left out for `along`, where it has no meaning. */
export interface LayoutOptions {
  orientation: Orientation;
  layout_preset?: Preset;
}

/** The tape width in mm: the printer's own number when it gave one, else read from the tape text. */
export function tapeMmOfStatus(status: Pick<PrinterStatus, "tape_loaded" | "tape_width_mm"> | null | undefined): number {
  return typeof status?.tape_width_mm === "number" ? status.tape_width_mm : tapeMmOf(status?.tape_loaded);
}

/** The stored default for one tape width, with the tape default filling what is not stored. */
export function layoutDefaultFor(stored: StoredDefaults, widthMm: number): LayoutChoice {
  const entry = stored?.[String(widthMm)];
  return {
    orientation: entry?.orientation ?? TAPE_DEFAULT.orientation,
    preset: entry?.preset ?? TAPE_DEFAULT.preset,
  };
}

/** The layout choice exists for a Brother QL with 62 mm tape loaded, and nowhere else. */
export const hasLayoutChoice = (printer: Pick<Printer, "backend"> | null | undefined, widthMm: number): boolean =>
  printer?.backend === "brother_ql" && widthMm === QL_WIDE_MM;

export const toOptions = ({ orientation, preset }: LayoutChoice): LayoutOptions =>
  orientation === "across" ? { orientation, layout_preset: preset } : { orientation };

export interface LabelLayout {
  /** The choice applies (QL, 62 mm); everything below is meaningless otherwise. */
  active: boolean;
  choice: LayoutChoice;
  setOrientation(next: Orientation): void;
  setPreset(next: Preset): void;
  /** What the job and the preview send; `undefined` when there is no choice, so those requests stay as they were. */
  options: LayoutOptions | undefined;
}

/**
 * The layout of the label for the printer and tape the dialog is about. Preselected from the printer's stored
 * default for the loaded width; a person's pick holds until the printer or the tape width changes.
 */
export function useLabelLayout(printer: Printer | null | undefined, widthMm: number): LabelLayout {
  const active = hasLayoutChoice(printer, widthMm);
  const scope = `${printer?.id ?? ""}:${widthMm}`;
  const [picked, setPicked] = useState<{ scope: string; value: Partial<LayoutChoice> }>({ scope, value: {} });
  const stored = layoutDefaultFor(printer?.layout_defaults, widthMm);
  const mine = picked.scope === scope ? picked.value : {};
  const choice: LayoutChoice = { ...stored, ...mine };
  return {
    active,
    choice,
    setOrientation: (orientation) => setPicked({ scope, value: { ...mine, orientation } }),
    setPreset: (preset) => setPicked({ scope, value: { ...mine, preset } }),
    options: active ? toOptions(choice) : undefined,
  };
}

/** A value that follows `value` after it has held still for `ms`; the first value is there at once. */
export function useDebounced<T>(value: T, ms: number): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    if (Object.is(settled, value)) return;
    const timer = setTimeout(() => setSettled(value), ms);
    return () => clearTimeout(timer);
  }, [value, ms, settled]);
  return settled;
}
