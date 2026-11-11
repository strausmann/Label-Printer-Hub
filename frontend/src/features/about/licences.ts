import { useQueries } from "@tanstack/react-query";

export type LicenceEntry = {
  name: string;
  version: string;
  licence: string;
  /** The licence text the package ships; `null` when it ships none. */
  text: string | null;
  part: "web" | "server";
};

/** Static files written by the image build (`licenses/frontend.json`, `licenses/backend.json`), not API paths. */
export const LICENCE_URLS: Record<LicenceEntry["part"], string> = {
  web: "/licenses/frontend.json",
  server: "/licenses/backend.json",
};

const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);
const nonEmpty = (value: unknown): value is string => typeof value === "string" && value.trim() !== "";

/** What the build wrote, made safe: anything that is not a list gives none, a record without name and version is dropped. */
export function parseLicenceList(raw: unknown, part: LicenceEntry["part"]): LicenceEntry[] {
  if (!Array.isArray(raw)) return [];
  const entries: LicenceEntry[] = [];
  for (const record of raw as unknown[]) {
    if (!isRecord(record) || !nonEmpty(record.name) || !nonEmpty(record.version)) continue;
    entries.push({
      name: record.name,
      version: record.version,
      licence: typeof record.license === "string" ? record.license : "",
      text: nonEmpty(record.licenseText) ? record.licenseText : null,
      part,
    });
  }
  return entries;
}

/**
 * One list. `"missing"` for everything that is not a JSON list the build wrote: a 404, the app shell (`text/html`)
 * that the SPA fallback answers an unknown path with, a body that does not parse, a network error.
 */
export async function fetchLicenceList(url: string, part: LicenceEntry["part"]): Promise<LicenceEntry[] | "missing"> {
  try {
    const response = await fetch(url, { credentials: "same-origin" });
    if (!response.ok) return "missing";
    if (!(response.headers.get("content-type") ?? "").toLowerCase().includes("application/json")) return "missing";
    return parseLicenceList(await response.json(), part);
  } catch {
    return "missing";
  }
}

const byName = (a: LicenceEntry, b: LicenceEntry) =>
  a.name.toLowerCase().localeCompare(b.name.toLowerCase()) || a.version.localeCompare(b.version) || a.part.localeCompare(b.part);

const PARTS = ["web", "server"] as const;

type Combined = { entries: LicenceEntry[]; missing: Array<LicenceEntry["part"]>; isPending: boolean };

/** Both lists, merged and sorted by package name; which of them the build does not include. */
export function useLicenceLists(): Combined {
  return useQueries({
    queries: PARTS.map((part) => ({
      queryKey: ["licences", part],
      queryFn: () => fetchLicenceList(LICENCE_URLS[part], part),
      staleTime: Infinity,
      retry: false,
    })),
    // `combine` is re-run only when a result changes, so typing in the filter does not sort 300 records again.
    combine: (results): Combined => {
      const entries: LicenceEntry[] = [];
      const missing: Array<LicenceEntry["part"]> = [];
      results.forEach((result, index) => {
        if (result.data === "missing") missing.push(PARTS[index]!);
        else if (result.data) entries.push(...result.data);
      });
      return { entries: entries.sort(byName), missing, isPending: results.some((r) => r.isPending) };
    },
  });
}
