import { useLingui } from "@lingui/react/macro";
import { useState } from "react";
import { Button, ComboBox, Input, Label, ListBox, ListBoxItem, Popover } from "react-aria-components";
import type { components } from "../../api/schema.gen";
import { FIELD } from "../../shell/SignIn";
import { LABEL } from "../settings/controls";
import { foldForSearch, matchSheetType } from "./matchSheetType";
import { typePickerLabel } from "./typeLabel";

type SheetType = components["schemas"]["SheetTypeRead"];

interface Entry {
  id: string;
  text: string;
  type: SheetType | null;
}

export interface SheetTypeComboboxProps {
  label: string;
  /** The types to offer. Which ones (archived or not) is the caller's rule; this only shows them. */
  types: readonly SheetType[];
  /** Key of the chosen type, or the id of `noneOption`. */
  value: string;
  onChange: (key: string) => void;
  disabled?: boolean;
  /** A first entry that stands for "no type" ("Choose a sheet type", "Any sheet type"). It is not searchable. */
  noneOption?: { id: string; label: string } | undefined;
  /** Replaces the label format (`typePickerLabel`). */
  labelFor?: (type: SheetType, locale: string) => string;
}

/** The label with the part that matched the query marked. Folding keeps the character count, so the offsets carry over. */
function Highlighted({ text, query }: { text: string; query: string }) {
  const word = foldForSearch(query.trim()).split(/\s+/)[0] ?? "";
  const at = word ? foldForSearch(text).indexOf(word) : -1;
  if (at < 0) return <>{text}</>;
  const chars = Array.from(text);
  const end = at + Array.from(word).length;
  return (
    <>
      {chars.slice(0, at).join("")}
      <mark className="rounded-r1 bg-transparent font-bold text-ink underline decoration-2 underline-offset-2">{chars.slice(at, end).join("")}</mark>
      {chars.slice(end).join("")}
    </>
  );
}

/**
 * The sheet type picker: type to filter on key, vendor, product code, description or label size.
 * React Aria's combobox (WAI-ARIA 1.2: a text input that owns a listbox); the list is ours, so the filter is too.
 */
export function SheetTypeCombobox({ label, types, value, onChange, disabled, noneOption, labelFor }: SheetTypeComboboxProps) {
  const { t, i18n } = useLingui();
  // What the person typed; null while the box shows the chosen type.
  const [typed, setTyped] = useState<string | null>(null);
  const archivedWord = t`archived`;

  const entries: Entry[] = [
    ...(noneOption ? [{ id: noneOption.id, text: noneOption.label, type: null }] : []),
    ...types.map((x) => ({ id: x.key, text: labelFor ? labelFor(x, i18n.locale) : typePickerLabel(x, i18n.locale, archivedWord), type: x })),
  ];
  // A key the list does not know (a link to a type that is gone) is shown as it is.
  const chosen = entries.find((e) => e.id === value);
  const chosenText = chosen?.text ?? value;
  const query = typed?.trim() ?? "";
  const shown = query === "" ? entries : entries.filter((e) => e.type !== null && matchSheetType(e.type, query));
  const cleared = typed !== null && typed === "";

  return (
    <ComboBox
      className="group flex min-w-0 flex-col gap-1.5"
      items={shown}
      selectedKey={chosen ? value : null}
      inputValue={typed ?? chosenText}
      isDisabled={disabled}
      menuTrigger="focus"
      allowsEmptyCollection
      onInputChange={(text) => setTyped(text === chosenText ? null : text)}
      onSelectionChange={(key) => {
        // Typing makes React Aria let go of the selection; the value only changes when a type is picked.
        if (key === null) return;
        setTyped(null);
        onChange(String(key));
      }}
      onBlur={() => setTyped(null)}
    >
      <Label className={LABEL}>{label}</Label>
      <div className="relative">
        {/* 16 px at least (the theme's text-base is smaller): below that iOS zooms the page on focus. The title keeps a cut value readable. */}
        <Input
          className={`${FIELD} truncate pr-[5.5rem] text-[16px] disabled:opacity-60`}
          title={chosenText}
          autoCapitalize="none"
          autoCorrect="off"
          spellCheck={false}
          onKeyDownCapture={(e) => {
            // React Aria undoes a search on Escape by writing the chosen item's text back, read from the filtered list.
            // That list may not hold the chosen type, and the write is then an empty string. Escape means "back to the value".
            if (e.key === "Escape") setTimeout(() => setTyped(null), 0);
            // Enter on a search nobody has moved into takes the first match, so "type 4736, Enter" works.
            const first = shown[0];
            if (e.key === "Enter" && query !== "" && first && !e.currentTarget.getAttribute("aria-activedescendant")) {
              e.preventDefault();
              e.stopPropagation();
              setTyped(null);
              onChange(first.id);
            }
          }}
        />
        <div className="absolute inset-y-0 right-0 flex items-center">
          {typed !== null && !cleared ? (
            <Button
              slot={null}
              aria-label={t`Clear the search`}
              // Keep the focus in the field: a blur would put the chosen type back before the press arrives.
              onPointerDown={(e) => e.preventDefault()}
              onMouseDown={(e) => e.preventDefault()}
              onPress={() => setTyped("")}
              className="press flex size-11 items-center justify-center rounded-r2 text-ink-2 data-[focus-visible]:outline-3 data-[focus-visible]:outline-link"
            >
              <svg viewBox="0 0 12 12" width="12" height="12" aria-hidden="true" className="fill-none stroke-current stroke-2">
                <path d="M2.5 2.5 9.5 9.5M9.5 2.5 2.5 9.5" />
              </svg>
            </Button>
          ) : null}
          <Button
            aria-label={t`Show all sheet types`}
            className="press flex size-11 items-center justify-center rounded-r2 text-ink-2 data-[focus-visible]:outline-3 data-[focus-visible]:outline-link"
          >
            <svg viewBox="0 0 12 12" width="12" height="12" aria-hidden="true" className="fill-none stroke-current stroke-2">
              <path d="M2 4.5 6 8.5 10 4.5" />
            </svg>
          </Button>
        </div>
      </div>
      {/* Never taller than 45 % of the screen: on a phone the room below the field reaches under the tab bar. */}
      <Popover className="flex max-h-[min(24rem,45dvh)]! w-(--trigger-width) origin-(--trigger-anchor-point) flex-col rounded-r2 border border-line-strong bg-surface p-1 shadow-lg data-[entering]:animate-[popin_140ms_cubic-bezier(0.23,1,0.32,1)]">
        {/* The popover is as tall as the room beside the field; a long list scrolls inside it. */}
        <ListBox
          className="max-h-[inherit] overflow-y-auto overscroll-contain outline-none"
          renderEmptyState={() => <p className="px-3 py-3 text-ink-2">{t`No sheet type matches.`}</p>}
        >
          {(entry: Entry) => (
            <ListBoxItem
              id={entry.id}
              textValue={entry.text}
              // The name is the whole label, whatever the highlight splits it into.
              aria-label={entry.text}
              className="flex min-h-11 cursor-default items-center rounded-r1 px-3 py-1 text-ink outline-none [overflow-wrap:anywhere] data-[focused]:bg-sunken data-[selected]:font-bold"
            >
              {/* One element: the item is a flex row, and the highlight's pieces must not become columns. */}
              <span className="min-w-0">{query !== "" && entry.type ? <Highlighted text={entry.text} query={query} /> : entry.text}</span>
            </ListBoxItem>
          )}
        </ListBox>
      </Popover>
    </ComboBox>
  );
}
