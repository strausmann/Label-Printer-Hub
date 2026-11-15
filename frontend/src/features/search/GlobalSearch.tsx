// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useRouter } from "@tanstack/react-router";
import { useEffect, useRef, useState, type RefObject } from "react";
import { SearchIcon } from "../../shell/icons";
import { useIsDesktop } from "../../shell/useIsDesktop";
import { SearchDialog } from "./SearchDialog";
import { SearchResults } from "./SearchResults";
import { useSearch } from "./useSearch";

/** The inline field of a desktop: a field in the top bar with its list hanging below. */
function InlineSearch({ field }: { field: RefObject<HTMLInputElement | null> }) {
  const router = useRouter();
  const search = useSearch((result) => router.history.push(result.href));
  return (
    <div role="search" className="relative min-w-0 flex-1 lg:max-w-md lg:flex-none lg:basis-96">
      <SearchIcon width={18} height={18} className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-ink-3" />
      <input
        {...search.inputProps}
        ref={field}
        className="h-11 w-full rounded-r2 border border-line-strong bg-sunken pr-3 pl-10 text-ink placeholder:text-ink-3 focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-link [&::-webkit-search-cancel-button]:appearance-none"
      />
      <SearchResults
        search={search}
        className="z-30 max-h-[min(60dvh,calc(var(--vvh)-6rem))] lg:absolute lg:top-full lg:right-0 lg:left-0 lg:mt-1 overflow-y-auto rounded-r3 border border-line bg-surface p-1 shadow-lg"
      />
    </div>
  );
}

/**
 * The top-bar search. From 1024 px a field with suggestions from every registered source; below, a magnifier that opens a
 * search dialog (#320). `/` jumps to the field, or opens the dialog, from anywhere except a text field.
 */
export function GlobalSearch() {
  const desktop = useIsDesktop();
  const [dialogOpen, setDialogOpen] = useState(false);
  const field = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key !== "/" || event.ctrlKey || event.metaKey || event.altKey || event.defaultPrevented) return;
      const target = event.target;
      if (target instanceof HTMLElement && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName))) return;
      event.preventDefault();
      if (desktop) field.current?.focus();
      else setDialogOpen(true);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [desktop]);

  return desktop ? <InlineSearch field={field} /> : <SearchDialog isOpen={dialogOpen} onOpenChange={setDialogOpen} />;
}
