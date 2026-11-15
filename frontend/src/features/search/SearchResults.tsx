// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useLingui } from "@lingui/react/macro";
import { Fragment } from "react";
import type { SearchResult } from "./registry";
import type { Search } from "./useSearch";

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

/** The list of suggestions, grouped under headings; nothing while the list is closed. `className` places and sizes the box. */
export function SearchResults({ search, className }: { search: Search; className: string }) {
  const { t } = useLingui();
  if (!search.open) return null;
  const { results } = search;
  return (
    <div id={search.listId} role="listbox" aria-label={t`Search results`} className={className}>
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
              {...search.optionProps(index)}
              className="flex min-h-11 cursor-pointer items-center gap-2 rounded-r2 px-3 py-2 text-ink aria-selected:bg-accent-soft aria-selected:ring-2 aria-selected:ring-link aria-selected:ring-inset"
            >
              <Title result={result} />
              {result.detail && <span className="ml-auto shrink-0 text-small text-ink-3">{result.detail}</span>}
            </div>
          </Fragment>
        );
      })}
    </div>
  );
}
