// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useLingui } from "@lingui/react/macro";
import { useQueryClient } from "@tanstack/react-query";
import { useId, useRef, useState, type HTMLAttributes, type InputHTMLAttributes, type KeyboardEvent } from "react";
import { runSearch, type SearchResult } from "./registry";

export interface Search {
  value: string;
  results: SearchResult[];
  active: number;
  /** Is the list showing? (results exist and Escape has not closed them) */
  open: boolean;
  /** Everything the field needs except `ref` and `className`. */
  inputProps: InputHTMLAttributes<HTMLInputElement>;
  /** Everything an option needs except `className` and its content. */
  optionProps: (index: number) => HTMLAttributes<HTMLDivElement>;
  listId: string;
}

/**
 * The state and the keys of the search, shared by the inline field and the phone dialog: suggestions from every registered
 * source, arrows + Enter, and the first suggestion active so typing a code and pressing Enter opens the best guess.
 *
 * An Escape that closes the list is consumed (`preventDefault` and `stopPropagation`), so a dialog around the field stays
 * open for it; an Escape with no list open is left to propagate and closes the dialog.
 */
export function useSearch(onGo: (result: SearchResult) => void): Search {
  const { t } = useLingui();
  const queryClient = useQueryClient();
  const id = useId();
  const listId = `${id}-list`;
  const [value, setValue] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [active, setActive] = useState(0);
  const [dismissed, setDismissed] = useState(false);
  const latest = useRef(0);

  const open = results.length > 0 && !dismissed;

  const update = (next: string) => {
    setValue(next);
    setDismissed(false);
    setActive(0);
    const ticket = ++latest.current;
    if (next.trim() === "") {
      setResults([]);
      return;
    }
    void runSearch(next, { queryClient }).then((found) => {
      if (ticket === latest.current) setResults(found);
    });
  };

  const go = (result: SearchResult) => {
    latest.current++;
    setValue("");
    setResults([]);
    setActive(0);
    onGo(result);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Escape") {
      if (open) {
        event.preventDefault();
        event.stopPropagation();
        setDismissed(true);
      }
      return;
    }
    if (results.length === 0) return;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (dismissed) setDismissed(false);
      const step = event.key === "ArrowDown" ? 1 : -1;
      setActive((i) => (i + step + results.length) % results.length);
    } else if (event.key === "Enter" && open) {
      event.preventDefault();
      const chosen = results[active];
      if (chosen) go(chosen);
    }
  };

  return {
    value,
    results,
    active,
    open,
    listId,
    inputProps: {
      type: "search",
      role: "combobox",
      "aria-label": t`Search`,
      "aria-expanded": open,
      "aria-controls": open ? listId : undefined,
      "aria-autocomplete": "list",
      "aria-activedescendant": open && results[active] ? `${id}-opt-${active}` : undefined,
      placeholder: t`Search`,
      value,
      autoComplete: "off",
      autoCapitalize: "none",
      autoCorrect: "off",
      spellCheck: false,
      enterKeyHint: "go",
      onChange: (event) => update(event.target.value),
      onKeyDown,
    },
    optionProps: (index) => {
      const result = results[index]!;
      return {
        id: `${id}-opt-${index}`,
        role: "option",
        "aria-selected": index === active,
        // Focus stays in the field (combobox pattern); the option is only a pointer target.
        tabIndex: -1,
        onKeyDown: (event) => event.key === "Enter" && go(result),
        // The field keeps focus: pointer-down must not blur it before the click lands.
        onMouseDown: (event) => event.preventDefault(),
        onClick: () => go(result),
        onMouseEnter: () => setActive(index),
      };
    },
  };
}
