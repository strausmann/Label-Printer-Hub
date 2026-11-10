import { useLingui } from "@lingui/react/macro";
import { Label, Radio, RadioGroup, Text } from "react-aria-components";
import { PRESETS, type Orientation, type Preset } from "./ql";

const SEGMENT =
  "press flex min-h-11 min-w-0 cursor-pointer items-center justify-center rounded-r1 border border-transparent px-3 text-center text-small font-bold text-ink-2 transition-colors duration-150 " +
  "data-[selected]:border-line-strong data-[selected]:bg-surface data-[selected]:text-ink " +
  "data-[focus-visible]:outline-3 data-[focus-visible]:outline-offset-1 data-[focus-visible]:outline-link";
const TRACK = "grid auto-cols-fr grid-flow-col gap-0.5 rounded-r2 bg-sunken p-0.5";

/**
 * The two choices of a QL label on 62 mm tape: which way the label runs and, for across, how it is arranged
 * (Compact is the default). Controlled, so the print dialogs and the printer settings share one control.
 */
export function LayoutPicker({
  orientation,
  preset,
  onOrientation,
  onPreset,
}: {
  orientation: Orientation;
  preset: Preset;
  onOrientation(next: Orientation): void;
  onPreset(next: Preset): void;
}) {
  const { t } = useLingui();
  const presetNames: Record<Preset, string> = { compact: t`Compact`, small_qr: t`Small QR`, standard: t`Standard` };
  return (
    <div className="flex flex-col gap-4">
      <RadioGroup value={orientation} onChange={(v) => onOrientation(v as Orientation)} orientation="horizontal" className="flex flex-col gap-1.5">
        <Label className="font-bold">{t`Direction`}</Label>
        <div className={TRACK}>
          <Radio value="across" className={SEGMENT}>{t`Across`}</Radio>
          <Radio value="along" className={SEGMENT}>{t`Along`}</Radio>
        </div>
        <Text slot="description" className="text-small text-ink-2">
          {orientation === "across" ? t`The label runs across the 62 mm width of the tape.` : t`The label runs along the tape.`}
        </Text>
      </RadioGroup>
      {orientation === "across" ? (
        <RadioGroup value={preset} onChange={(v) => onPreset(v as Preset)} orientation="horizontal" className="flex flex-col gap-1.5">
          <Label className="font-bold">{t`Arrangement`}</Label>
          <div className={TRACK}>
            {PRESETS.map((p) => (
              <Radio key={p} value={p} className={SEGMENT}>
                {presetNames[p]}
              </Radio>
            ))}
          </div>
        </RadioGroup>
      ) : null}
    </div>
  );
}
