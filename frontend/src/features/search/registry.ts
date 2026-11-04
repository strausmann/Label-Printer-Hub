import type { QueryClient } from "@tanstack/react-query";

/** One line in the global search list; `href` is an in-app path. */
export interface SearchResult {
  id: string;
  /** Translated heading the result is listed under. */
  group: string;
  title: string;
  /** A part of `title` to set in the code font (a pasted ID, a label code). */
  code?: string;
  detail?: string;
  href: string;
}

export interface SearchContext {
  queryClient: QueryClient;
}

export interface SearchSource {
  id: string;
  /** Lower comes first; sources without one sort last. */
  order?: number;
  search(query: string, context: SearchContext): Promise<SearchResult[]>;
}

const sources = new Map<string, SearchSource>();

/** Adds a source (the same id replaces the earlier one); the returned function removes it. */
export function registerSearchSource(source: SearchSource): () => void {
  sources.set(source.id, source);
  return () => {
    if (sources.get(source.id) === source) sources.delete(source.id);
  };
}

export const getSearchSources = (): SearchSource[] =>
  [...sources.values()].sort((a, b) => (a.order ?? 1000) - (b.order ?? 1000) || a.id.localeCompare(b.id));

/** Asks every source; one that fails is skipped so it never blanks the others. */
export async function runSearch(query: string, context: SearchContext): Promise<SearchResult[]> {
  const q = query.trim();
  if (q === "") return [];
  const settled = await Promise.all(
    getSearchSources().map((s) => s.search(q, context).catch((): SearchResult[] => [])),
  );
  return settled.flat();
}
