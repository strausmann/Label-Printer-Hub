import { useLingui } from "@lingui/react/macro";
import { useCallback, useEffect, useRef, useState, type RefObject } from "react";
import { Button, Radio, RadioGroup } from "react-aria-components";
import { PANEL, PRIMARY_BUTTON, SECONDARY_BUTTON, SECTION_HEADING } from "../ui";
import { isRollChanged, useRoll, useSetRollColour, type Printer, type PrinterStatus, type Roll, type RollColour } from "./api";
import { isTapeColour, TAPE_COLOURS, useColourNames, type TapeColour } from "./model";
import { ColourSwatch } from "./TapeSwatch";

const FOCUS = "data-[focus-visible]:outline-3 data-[focus-visible]:outline-offset-2 data-[focus-visible]:outline-link";
const CHOICE = `press inline-flex min-h-11 min-w-0 cursor-pointer items-center gap-2 rounded-r2 border border-line-strong bg-surface px-3 text-small font-bold text-ink transition-colors duration-150 hover:bg-sunken data-[selected]:border-ink data-[selected]:bg-sunken data-[disabled]:opacity-60 ${FOCUS}`;

/**
 * The colour choices of a roll: one radio group and a separate Save. Picking a colour only marks it
 * (a slip of the finger on a phone must not colour the roll), Save sends it. The answer goes out with
 * the width and media text this question is about, so a question that went stale while a new roll was
 * inserted is refused (409) instead of colouring the wrong roll.
 */
function ColourChoices({
  printerId,
  roll,
  current,
  secondary,
  onDone,
  focusOnMount = false,
}: {
  printerId: string;
  roll: Roll;
  current: RollColour | null;
  /** The non-colour answer next to Save: "Skip" for a new roll, "Remove colour" when editing. It answers at once. */
  secondary: { label: string; hint?: string };
  onDone: () => void;
  /** Edit mode moves focus to the current colour (or the first); the new-roll prompt never steals it. */
  focusOnMount?: boolean;
}) {
  const { t } = useLingui();
  const names = useColourNames();
  const set = useSetRollColour(printerId);
  const [picked, setPicked] = useState<TapeColour | null>(current);
  const [changedAgain, setChangedAgain] = useState(false);
  const group = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!focusOnMount) return;
    const radios = group.current?.querySelectorAll<HTMLInputElement>('input[type="radio"]') ?? [];
    (Array.from(radios).find((r) => r.checked) ?? radios[0])?.focus();
  }, [focusOnMount]);

  const send = (colour: RollColour | null) => {
    setChangedAgain(false);
    set.mutate(
      { colour, width_mm: roll.width_mm ?? null, media_raw: roll.media_raw ?? null },
      {
        onSuccess: onDone,
        // The status and roll are read again; the question that comes back is about the new roll.
        onError: (error) => {
          const again = isRollChanged(error);
          setChangedAgain(again);
          // The colour that was marked belonged to the old roll.
          if (again) setPicked(null);
        },
      },
    );
  };
  const failed = set.isError && !changedAgain;

  return (
    <div className="flex flex-col gap-3">
      {changedAgain && <p role="alert" className="text-small font-bold">{t`The roll changed again while you were choosing. Pick the colour of the new roll.`}</p>}
      {failed && <p role="alert" className="text-small font-bold text-bad">{t`The colour could not be saved. Try again.`}</p>}
      <div ref={group}>
        <RadioGroup
          aria-label={t`Tape colour`}
          orientation="horizontal"
          value={picked}
          onChange={(value) => {
            if (isTapeColour(value)) setPicked(value);
          }}
          isDisabled={set.isPending}
          className="grid grid-cols-2 gap-2 min-[480px]:grid-cols-4"
        >
          {TAPE_COLOURS.map((colour) => (
            <Radio key={colour} value={colour} className={CHOICE}>
              <ColourSwatch colour={colour} />
              <span className="[overflow-wrap:anywhere]">{names[colour]}</span>
            </Radio>
          ))}
        </RadioGroup>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button className={PRIMARY_BUTTON} isDisabled={set.isPending || picked === null || picked === current} onPress={() => picked !== null && send(picked)}>
          {t`Save`}
        </Button>
        <Button className={`${SECONDARY_BUTTON} min-w-0 [overflow-wrap:anywhere]`} isDisabled={set.isPending} onPress={() => send(null)}>
          {secondary.label}
        </Button>
      </div>
      {secondary.hint && <p className="text-small text-ink-2">{secondary.hint}</p>}
    </div>
  );
}

/** What stands in for the colour choices until the roll is known: a short wait, or the failure with a way out. */
function RollUnavailable({ roll }: { roll: { isError: boolean; refetch: () => unknown } }) {
  const { t } = useLingui();
  if (!roll.isError) return <p role="status" className="text-small text-ink-2">{t`Loading…`}</p>;
  return (
    <div className="flex flex-col items-start gap-2">
      <p role="alert" className="text-small font-bold text-bad">{t`The roll could not be read.`}</p>
      <Button className={SECONDARY_BUTTON} onPress={() => void roll.refetch()}>{t`Retry`}</Button>
    </div>
  );
}

/**
 * Shown above the material when the roll was changed and nobody gave its colour yet. The printer
 * cannot read the colour, so the operator is asked once per roll. Only for keys that may write.
 */
export function RollColourPrompt({ printer, status, onDone }: { printer: Printer; status: PrinterStatus | undefined; onDone: () => void }) {
  const { t } = useLingui();
  const roll = useRoll(printer.id, status?.roll_prompt === true);
  if (status?.roll_prompt !== true) return null;
  const width = roll.data?.width_mm;
  return (
    <section aria-labelledby="roll-prompt-h" className={`${PANEL} flex flex-col gap-3 border-2 border-accent bg-accent-soft`}>
      <div className="flex flex-col gap-1">
        <h2 id="roll-prompt-h" className={SECTION_HEADING}>{t`The roll was changed`}</h2>
        <p className="text-small [overflow-wrap:anywhere]">
          {typeof width === "number"
            ? t`You put in a ${width} mm roll. The printer does not report the tape colour. Which colour is it?`
            : t`You put in a new roll. The printer does not report the tape colour. Which colour is it?`}
        </p>
      </div>
      {roll.data ? (
        <ColourChoices
          printerId={printer.id}
          roll={roll.data}
          current={null}
          secondary={{ label: t`Skip`, hint: t`You can set the colour later on this page.` }}
          onDone={onDone}
        />
      ) : (
        <RollUnavailable roll={roll} />
      )}
    </section>
  );
}

/** In the material block: set, change or remove the colour of the loaded roll. */
export function RollColourEdit({
  printer,
  status,
  triggerRef,
}: {
  printer: Printer;
  status: PrinterStatus | undefined;
  triggerRef: RefObject<HTMLButtonElement | null>;
}) {
  const { t } = useLingui();
  const [open, setOpen] = useState(false);
  const roll = useRoll(printer.id, open);
  const colour = status?.tape_colour ?? null;
  // Whether the keyboard focus sits inside the open panel (a panel that is removed fires no blur of its own).
  const focusInside = useRef(false);
  // Stable, so the Escape handler below subscribes once per opening and not on every render.
  const close = useCallback(() => {
    setOpen(false);
    focusInside.current = false;
    // The choices go away with the focus on them: hand it back to the control that opened them.
    queueMicrotask(() => triggerRef.current?.focus());
  }, [triggerRef]);
  // A new roll question replaces the panel: the colour it would edit belongs to the roll that was just taken out.
  // The panel closes without a rebinding to the new roll.
  const prompted = status?.roll_prompt === true;
  const [wasPrompted, setWasPrompted] = useState(prompted);
  if (prompted !== wasPrompted) {
    setWasPrompted(prompted);
    if (prompted) setOpen(false);
  }
  useEffect(() => {
    if (!prompted || !focusInside.current) return;
    focusInside.current = false;
    triggerRef.current?.focus();
  }, [prompted, triggerRef]);
  // Escape closes the choices for a keyboard-only operator.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, close]);
  return (
    <div className="flex flex-col gap-3">
      <Button ref={triggerRef} className={`${SECONDARY_BUTTON} self-start`} aria-expanded={open} onPress={() => (open ? close() : setOpen(true))}>
        {colour ? t`Change colour` : t`Set colour`}
      </Button>
      {open && !roll.data && <RollUnavailable roll={roll} />}
      {open && roll.data && (
        <div
          className="flex flex-col gap-3"
          onFocus={() => (focusInside.current = true)}
          onBlur={(event) => {
            if (!event.currentTarget.contains(event.relatedTarget)) focusInside.current = false;
          }}
        >
          <ColourChoices
            printerId={printer.id}
            roll={roll.data}
            current={colour}
            secondary={{ label: t`Remove colour` }}
            onDone={close}
            focusOnMount
          />
          <Button className={`${SECONDARY_BUTTON} self-start`} onPress={close}>{t`Cancel`}</Button>
        </div>
      )}
    </div>
  );
}
