// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useLingui } from "@lingui/react/macro";
import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "@tanstack/react-router";
import { Fragment, useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { SearchIcon } from "../../shell/icons";
import { runSearch, type SearchResult } from "./registry";

/** The title with its `code` part (if any) set in the code font. */
function Title({ result }: { result: SearchResult }) {
  const { code, title } = result;
  const at = code ? title.indexOf(code) : -1;
  if (!code || at < 0) return <span className="truncate">{title}</span>;
  return (
    <span className="truncate">
      {title.slice(0, at)}
      <code className="text-ink">{code}</code>
      {title.slice(at + code.length)}
    </span>
  );
}

/**
 * The top-bar search: one field, suggestions from every registered source (arrows + Enter).
 * The first suggestion is active, so typing a code and pressing Enter opens the best guess.
 */
export function GlobalSearch() {
  const { t } = useLingui();
  const router = useRouter();
  const queryClient = useQueryClient();
  const id = useId();
  const listId = `${id}-list`;
  const [value, setValue] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [active, setActive] = useState(0);
  const [dismissed, setDismissed] = useState(false);
  const latest = useRef(0);
  const field = useRef<HTMLInputElement>(null);

  // `/` jumps to the search from anywhere, except while the person is typing in a field.
  useEffect(() => {
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key !== "/" || event.ctrlKey || event.metaKey || event.altKey || event.defaultPrevented) return;
      const target = event.target;
      if (target instanceof HTMLElement && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName))) return;
      event.preventDefault();
      field.current?.focus();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

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
    router.history.push(result.href);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Escape") {
      if (open) {
        event.preventDefault();
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

  return (
    <div role="search" className="relative min-w-0 flex-1 lg:max-w-md lg:flex-none lg:basis-96">
      <SearchIcon width={18} height={18} className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-ink-3" />
      <input
        ref={field}
        type="search"
        role="combobox"
        aria-label={t`Search`}
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        aria-autocomplete="list"
        aria-activedescendant={open && results[active] ? `${id}-opt-${active}` : undefined}
        placeholder={t`Search`}
        value={value}
        autoComplete="off"
        autoCapitalize="none"
        autoCorrect="off"
        spellCheck={false}
        enterKeyHint="go"
        onChange={(event) => update(event.target.value)}
        onKeyDown={onKeyDown}
        className="h-11 w-full rounded-r2 border border-line-strong bg-sunken pr-3 pl-10 text-ink placeholder:text-ink-3 focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-link [&::-webkit-search-cancel-button]:appearance-none"
      />
      {open && (
        <div
          id={listId}
          role="listbox"
          aria-label={t`Search results`}
          className="z-30 max-h-[min(60dvh,calc(var(--vvh)-6rem))] max-lg:fixed max-lg:top-[calc(4.25rem+var(--vv-top))] max-lg:right-4 max-lg:left-4 lg:absolute lg:top-full lg:right-0 lg:left-0 lg:mt-1 overflow-y-auto rounded-r3 border border-line bg-surface p-1 shadow-lg"
        >
          {results.map((result, index) => {
            const heading = result.group !== results[index - 1]?.group ? result.group : null;
            return (
              <Fragment key={`${result.group}-${result.id}`}>
                {heading && (
                  <p role="presentation" className={`px-3 pb-1 text-small font-bold text-ink-3 ${index === 0 ? "pt-2" : "pt-3"}`}>
                    {heading}
                  </p>
                )}
                <div
                  id={`${id}-opt-${index}`}
                  role="option"
                  aria-selected={index === active}
                  // Focus stays in the field (combobox pattern); the option is only a pointer target.
                  tabIndex={-1}
                  onKeyDown={(event) => event.key === "Enter" && go(result)}
                  // The field keeps focus: pointer-down must not blur it before the click lands.
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={() => go(result)}
                  onMouseEnter={() => setActive(index)}
                  className="flex min-h-11 cursor-pointer items-center gap-2 rounded-r2 px-3 py-2 text-ink aria-selected:bg-accent-soft aria-selected:ring-2 aria-selected:ring-link aria-selected:ring-inset"
                >
                  <Title result={result} />
                  {result.detail && <span className="ml-auto shrink-0 text-small text-ink-3">{result.detail}</span>}
                </div>
              </Fragment>
            );
          })}
        </div>
      )}
    </div>
  );
}
