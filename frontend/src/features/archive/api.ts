import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../../api/client";
import type { components } from "../../api/schema.gen";
import { queryString } from "../../api/queryString";
import { sheetsListKey, typeKey, typesKey, typesListKey } from "../sheets/keys";

export { typeKey, typesKey } from "../sheets/keys";

type Schemas = components["schemas"];
export type SheetTypeRead = Schemas["SheetTypeRead"];
export type SheetTypeDetail = Schemas["SheetTypeDetail"];
export type SheetTypeCreate = Schemas["SheetTypeCreate"];
export type SheetTypePatch = Schemas["SheetTypePatch"];
export type VersionCreate = Schemas["VersionCreate"];
export type VersionRead = Schemas["VersionRead"];
export type ExportDoc = Schemas["ExportDoc"];
export type ImportResponse = Schemas["ImportResponse"];

export interface TypeFilters {
  page?: "A4" | "Letter";
  vendor?: string;
  q?: string;
  /** Label width in mm, ±0.5. */
  w?: number;
  /** Label height in mm, ±0.5. */
  h?: number;
  include_archived?: boolean;
}

/** How an import treats a type whose key exists: refuse, add a version, or store it under a new key. */
export interface ImportOptions {
  mode?: "strict" | "new_version" | "as_new_key";
  new_key?: string;
  new_prefix?: string;
}

const encode = encodeURIComponent;
const typePath = (key: string) => `/api/sheet-types/${encode(key)}`;

export const useSheetTypes = (filters: TypeFilters = {}) =>
  useQuery({
    queryKey: typesKey(filters),
    queryFn: () => apiFetch<SheetTypeRead[]>(`/api/sheet-types${queryString({ ...filters })}`),
  });

export const useSheetType = (key: string, enabled = true) =>
  useQuery({ queryKey: typeKey(key), queryFn: () => apiFetch<SheetTypeDetail>(typePath(key)), enabled });

/**
 * A type write changes the lists, the type and (through the usage counts) the sheet lists.
 * `keyOf` names the type that changed: from the request, or (an import) from the answer.
 */
function useTypeWrite<V, R>(run: (v: V) => Promise<R>, keyOf: (v: V, data: R | undefined) => string | null) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: run,
    onSettled: (data, _error, v) => {
      void client.invalidateQueries({ queryKey: typesListKey });
      void client.invalidateQueries({ queryKey: sheetsListKey });
      const key = keyOf(v, data);
      if (key) void client.invalidateQueries({ queryKey: typeKey(key) });
    },
  });
}

export const useCreateType = () =>
  useTypeWrite((body: SheetTypeCreate) => apiFetch<SheetTypeRead>("/api/sheet-types", { method: "POST", json: body }), () => null);

export const usePatchType = () =>
  useTypeWrite(
    ({ key, patch }: { key: string; patch: SheetTypePatch }) =>
      apiFetch<SheetTypeRead>(typePath(key), { method: "PATCH", json: patch }),
    (v) => v.key,
  );

export const useAddVersion = () =>
  useTypeWrite(
    ({ key, version }: { key: string; version: VersionCreate }) =>
      apiFetch<VersionRead>(`${typePath(key)}/versions`, { method: "POST", json: version }),
    (v) => v.key,
  );

/** Archives a type, or brings it back with `unarchive: true`. */
export const useArchiveType = () =>
  useTypeWrite(
    ({ key, unarchive = false }: { key: string; unarchive?: boolean }) =>
      apiFetch<SheetTypeRead>(`${typePath(key)}/${unarchive ? "unarchive" : "archive"}`, { method: "POST" }),
    (v) => v.key,
  );

export const useDeleteType = () =>
  useTypeWrite((key: string) => apiFetch<void>(typePath(key), { method: "DELETE" }), (key) => key);

/** The download address of a type's export file (a version, or the current one). */
export function exportTypeUrl(key: string, version?: number | null): string {
  return `${typePath(key)}/export${queryString({ version })}`;
}

export const useImportType = () =>
  useTypeWrite(
    ({ doc, options = {} }: { doc: ExportDoc; options?: ImportOptions }) =>
      apiFetch<ImportResponse>(`/api/sheet-types/import${queryString({ ...options })}`, { method: "POST", json: doc }),
    // The type the import touched: a new version changes an open detail, a new key has none cached yet.
    (_v, data) => data?.key ?? null,
  );
