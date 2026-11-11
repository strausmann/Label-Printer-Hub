import { useLingui } from "@lingui/react/macro";
import { useEffect, useRef, useState } from "react";
import { Button, ComboBox, Input, Label, ListBox, ListBoxItem, Popover } from "react-aria-components";
import type { components } from "../../api/schema.gen";
import { FIELD } from "../../shell/SignIn";
import { listRoom, perFrame, readViewport, sameRoom, subscribeViewport, type ListRoom } from "../../shell/viewport";
import { LABEL } from "../settings/controls";
import { foldForSearch, foldWithMap, matchSheetType } from "./matchSheetType";
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

/** The tallest the list gets (px) and the gap it keeps to the screen edge and the tab bar. */
const LIST_MAX = 384;
const LIST_GAP = 12;
/** How long the dialog frame must have stopped scrolling before a list that its scroll closed is opened again (ms). */
const QUIET = 150;
/** A close this soon after Escape, a choice or a press on the arrow is the person's, not a scroll's (ms). */
const PERSON = 300;
/** What a field sits in when it is in a dialog. */
const DIALOG = '[role="dialog"], [role="alertdialog"]';

/** The label with the part that matched the query marked. Folding drops spaces (around "×"), so the match is mapped back to the label's own offsets. */
function Highlighted({ text, query }: { text: string; query: string }) {
  const word = foldForSearch(query.trim()).split(/\s+/)[0] ?? "";
  const { folded, origin } = foldWithMap(text);
  const found = word ? folded.indexOf(word) : -1;
  if (found < 0) return <>{text}</>;
  const chars = Array.from(text);
  const at = origin[found]!;
  const end = origin[found + Array.from(word).length - 1]! + 1;
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
  // "Choose a sheet type" / "Any sheet type" stand for no choice: they are the placeholder, never text the person would have to delete.
  const isNone = !!noneOption && value === noneOption.id;
  const shownText = isNone ? "" : chosenText;
  const query = typed?.trim() ?? "";
  const shown = query === "" ? entries : entries.filter((e) => e.type !== null && matchSheetType(e.type, query));
  const cleared = typed !== null && typed === "";
  const trigger = useRef<HTMLButtonElement>(null);
  const hadFocus = useRef(false);
  const typedRef = useRef(typed);
  useEffect(() => {
    typedRef.current = typed;
  }, [typed]);
  // Where the list goes and how tall it may get. React Aria measures against the whole page, not the screen, so the list
  // would run past the bottom edge, under the fixed tab bar of a phone and under the on-screen keyboard. This measures what
  // is visible: when the list opens, and again while it is open, because the keyboard comes up after the focus opened it.
  const field = useRef<HTMLDivElement>(null);
  const [room, setRoom] = useState<ListRoom>({ placement: "bottom start", maxHeight: LIST_MAX });
  const [open, setOpen] = useState(false);
  const measure = () => {
    if (!field.current) return;
    // The tab bar of a phone limits the list, but not inside a dialog: the dialog covers it, and with the keyboard open
    // the bar sits right above the keyboard, so counting it would take a strip of the room off for nothing.
    const bar = field.current.closest(DIALOG) ? null : document.querySelector("[data-tabbar]");
    const lowest = bar && getComputedStyle(bar).display !== "none" ? bar.getBoundingClientRect().top : undefined;
    const next = listRoom(field.current.getBoundingClientRect(), readViewport(), { lowest, gap: LIST_GAP, max: LIST_MAX, option: 44 });
    setRoom((prev) => (sameRoom(prev, next) ? prev : next));
  };
  // React Aria closes a list that is not modal when an ancestor of the field scrolls. Inside a dialog that ancestor is the
  // dialog's own frame, and the browser scrolls it when it brings the field above the keyboard, so the list would close
  // the moment the keyboard comes up. A close that comes with such a scroll is undone, but only
  //  - when nothing else closed it (Escape, a choice, the arrow button: `person`),
  //  - once the scrolling has been quiet for `QUIET` ms (a finger still scrolling is not overruled), and
  //  - once per focus.
  const scroll = useRef({ last: -Infinity, armed: false, reopened: false, person: -Infinity, timer: 0, check: 0 });
  const settle = () => {
    const state = scroll.current;
    window.clearTimeout(state.timer);
    state.timer = window.setTimeout(() => {
      state.armed = false;
      const input = field.current?.querySelector("input");
      if (input && input === document.activeElement && input.getAttribute("aria-expanded") === "false") {
        state.reopened = true;
        trigger.current?.click();
      }
    }, QUIET);
  };
  useEffect(() => {
    const state = scroll.current;
    const note = (event: Event) => {
      // The text field scrolls inside itself while a long query is typed; that is not what is meant.
      if (event.target instanceof HTMLInputElement) return;
      state.last = performance.now();
      if (state.armed) settle();
    };
    document.addEventListener("scroll", note, true);
    return () => {
      document.removeEventListener("scroll", note, true);
      window.clearTimeout(state.timer);
      window.clearTimeout(state.check);
    };
  }, []);
  // Marks a close that is about to happen (or just happened) as the person's doing: Escape, a choice, the arrow button.
  const closedByPerson = () => {
    scroll.current.person = performance.now();
  };
  const stopReopening = () => {
    const state = scroll.current;
    state.armed = false;
    window.clearTimeout(state.timer);
    window.clearTimeout(state.check);
  };
  const listClosed = () => {
    const state = scroll.current;
    // Only in a dialog: on a page a scroll that closes the list is the expected behaviour (the field moved away).
    if (state.reopened || !field.current?.closest(DIALOG)) return;
    const closedAt = performance.now();
    // React Aria closes inside the scroll event; ours may come a moment later, so look back a little and ahead a little.
    window.clearTimeout(state.check);
    state.check = window.setTimeout(() => {
      // The person's mark may come a moment after the close (a press handler runs after the one that closes the list).
      if (state.person >= closedAt - PERSON) return;
      if (state.last < closedAt - 50) return;
      state.armed = true;
      settle();
    }, 20);
  };
  const measureRef = useRef(measure);
  useEffect(() => {
    measureRef.current = measure;
  });
  // While the list is open: measure again when the visible area changes (the keyboard comes up after the focus opened the
  // list). A scroll needs no measuring of its own: it closes the list, and opening it again measures (see above).
  useEffect(() => {
    if (!open) return;
    const again = perFrame(() => measureRef.current());
    const stop = subscribeViewport(again.run);
    return () => {
      stop();
      again.cancel();
    };
  }, [open]);

  return (
    <ComboBox
      className="group flex min-w-0 flex-col gap-1.5"
      items={shown}
      selectedKey={chosen ? value : null}
      inputValue={typed ?? shownText}
      isDisabled={disabled}
      menuTrigger="focus"
      allowsEmptyCollection
      onOpenChange={(isOpen) => {
        setOpen(isOpen);
        if (isOpen) {
          stopReopening();
          measure();
        } else listClosed();
      }}
      onInputChange={(text) => setTyped(text === shownText ? null : text)}
      onSelectionChange={(key) => {
        // Typing makes React Aria let go of the selection; the value only changes when a type is picked.
        if (key === null) return;
        closedByPerson();
        setTyped(null);
        onChange(String(key));
      }}
      onBlur={() => {
        setTyped(null);
        stopReopening();
        scroll.current.reopened = false;
      }}
    >
      <Label className={LABEL}>{label}</Label>
      <div ref={field} className="relative">
        {/* 16 px at least (the theme's text-base is smaller): below that iOS zooms the page on focus. The title keeps a cut value readable. */}
        <Input
          className={`${FIELD} truncate pr-[5.5rem] text-[16px] disabled:opacity-60`}
          title={chosenText}
          placeholder={isNone ? noneOption?.label : chosenText}
          autoCapitalize="none"
          autoCorrect="off"
          spellCheck={false}
          // Focus starts a new query: the shown label is selected, so the first keystroke replaces it. Selecting again on the
          // next tick is for iOS, which drops a selection made inside the focus event.
          onFocus={(e) => {
            const input = e.currentTarget;
            // The input gets the focus again when the list opens under the first keystroke: by then there is a query, leave it be.
            if (typedRef.current !== null) return;
            input.select();
            setTimeout(() => {
              if (typedRef.current === null) input.select();
            }, 0);
          }}
          // A tap on a field that already has the focus (the list was closed by a choice or a drag) opens it again.
          // A tap that only just gave it the focus opens the list through the focus; this is the tap that found the focus already there.
          onPointerDown={(e) => {
            hadFocus.current = document.activeElement === e.currentTarget;
          }}
          onClick={(e) => {
            if (!hadFocus.current || e.currentTarget.getAttribute("aria-expanded") !== "false") return;
            const input = e.currentTarget;
            trigger.current?.click();
            // A new search, as with a fresh focus; after the click, because opening the list moves the caret.
            const select = () => {
              if (typedRef.current === null) input.select();
            };
            select();
            setTimeout(select, 0);
          }}
          onKeyDownCapture={(e) => {
            // React Aria undoes a search on Escape by writing the chosen item's text back, read from the filtered list.
            // That list may not hold the chosen type, and the write is then an empty string. Escape means "back to the value".
            if (e.key === "Escape") {
              closedByPerson();
              setTimeout(() => setTyped(null), 0);
            }
            // Enter on a search nobody has moved into takes the first match, so "type 4736, Enter" works.
            const first = shown[0];
            if (e.key === "Enter" && query !== "" && first && !e.currentTarget.getAttribute("aria-activedescendant")) {
              e.preventDefault();
              e.stopPropagation();
              closedByPerson();
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
            ref={trigger}
            // Only a press that closes an open list is the person's doing; one that opens it brings up the keyboard, and the
            // scroll that follows must still be undone.
            onPressStart={() => {
              if (field.current?.querySelector("input")?.getAttribute("aria-expanded") === "true") closedByPerson();
            }}
            aria-label={t`Show all sheet types`}
            className="press flex size-11 items-center justify-center rounded-r2 text-ink-2 data-[focus-visible]:outline-3 data-[focus-visible]:outline-link"
          >
            <svg viewBox="0 0 12 12" width="12" height="12" aria-hidden="true" className="fill-none stroke-current stroke-2">
              <path d="M2 4.5 6 8.5 10 4.5" />
            </svg>
          </Button>
        </div>
      </div>
      <Popover placement={room.placement} maxHeight={room.maxHeight} shouldFlip={false} offset={4} className="flex w-(--trigger-width) origin-(--trigger-anchor-point) flex-col rounded-r2 border border-line-strong bg-surface p-1 shadow-lg data-[entering]:animate-[popin_140ms_cubic-bezier(0.23,1,0.32,1)]">
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
