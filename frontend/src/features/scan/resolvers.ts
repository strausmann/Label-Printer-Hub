import { parseLabelPath } from "../lookup/labelUrl";
import type { ScanHit } from "./decoder";

export interface ScanResolver {
  id: string;
  match(hit: ScanHit): boolean;
  /** The in-app route the code leads to. */
  resolve(hit: ScanHit): string;
}

export interface ScanResolution {
  resolverId: string;
  route: string;
}

const resolvers = new Map<string, ScanResolver>();

/**
 * Adds a resolver (the same id replaces the earlier one); the returned function removes it.
 * Modules register theirs (a sheet, an ASN, a label code) and decide where a scan leads.
 */
export function registerScanResolver(resolver: ScanResolver): () => void {
  resolvers.set(resolver.id, resolver);
  return () => {
    if (resolvers.get(resolver.id) === resolver) resolvers.delete(resolver.id);
  };
}

/** The first resolver that claims the code; foundation ones are asked first. */
export function resolveScan(hit: ScanHit): ScanResolution | null {
  for (const resolver of resolvers.values()) {
    if (resolver.match(hit)) return { resolverId: resolver.id, route: resolver.resolve(hit) };
  }
  return null;
}

const JOB_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// A label link is read by the parser the integration start page uses, so a printed label and a
// pasted one always mean the same item. Its host is ignored.
registerScanResolver({
  id: "label-link",
  match: (hit) => parseLabelPath(hit.text) !== null,
  resolve: (hit) => {
    const label = parseLabelPath(hit.text)!;
    return `/${label.kind}/${encodeURIComponent(label.id)}`;
  },
});

registerScanResolver({
  id: "job-id",
  match: (hit) => JOB_ID.test(hit.text.trim()),
  resolve: (hit) => `/jobs/${hit.text.trim().toLowerCase()}`,
});
