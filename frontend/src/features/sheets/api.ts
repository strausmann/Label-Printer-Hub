import { keepPreviousData, useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { apiFetch } from "../../api/client";
import { queuedJobs } from "../../api/errorDetail";
import { queryString } from "../../api/queryString";
import type { components } from "../../api/schema.gen";
import { watchPrint } from "../jobs/printWatch";
import {
  marginCheckKey,
  nextCodeKey,
  SHEET_PREVIEW_KEY,
  sheetKey,
  sheetPreviewKey,
  sheetsKey,
  sheetsListKey,
  typesListKey,
  type SheetPrintRequest,
} from "./keys";

export {
  calibrationKey,
  capabilitiesKey,
  sheetKey,
  sheetPreviewKey,
  sheetsKey,
  sheetsListKey,
  typeKey,
  typesKey,
  typesListKey,
} from "./keys";
export type { SheetPrintRequest } from "./keys";

type Schemas = components["schemas"];
export type SheetRead = Schemas["SheetRead"];
export type SheetSummary = Schemas["SheetSummary"];
export type SheetCreate = Schemas["SheetCreate"];
export type SheetCreated = Schemas["SheetCreated"];
export type SheetPreview = Schemas["SheetPreview"];
export type SheetPrintResponse = Schemas["SheetPrintResponse"];
export type NextCode = Schemas["NextCode"];
export type MarginCheck = Schemas["MarginCheckRead"];
export type MarkedCellIn = Schemas["MarkedCellIn"];

export interface SheetFilters {
  type?: string;
  free_at_least?: number;
  state?: "active" | "full" | "discarded" | "all";
  q?: string;
}

const post = <T>(path: string, json?: unknown) => apiFetch<T>(path, { method: "POST", json });
const encode = encodeURIComponent;

export const useSheets = (filters: SheetFilters = {}, enabled = true) =>
  useQuery({
    queryKey: sheetsKey(filters),
    queryFn: () => apiFetch<SheetSummary[]>(`/api/v1/sheets${queryString({ ...filters })}`),
    enabled,
  });

export const useSheet = (code: string) =>
  useQuery({
    queryKey: sheetKey(code),
    queryFn: () => apiFetch<SheetRead>(`/api/v1/sheets/${encode(code)}`),
    enabled: !!code,
  });

/** The code the next sheet of this type will get, and a hint for the ID placement. */
export const useNextCode = (typeKey: string | null) =>
  useQuery({
    queryKey: nextCodeKey(typeKey ?? ""),
    queryFn: () => apiFetch<NextCode>(`/api/v1/sheets/next-code${queryString({ type: typeKey })}`),
    enabled: !!typeKey,
  });

/** Whether the margin can hold the sheet ID on this printer and tray (the band depends on the tray's calibration). */
export const useMarginCheck = (typeKey: string | null, printer: string | null, tray: string | null) =>
  useQuery({
    queryKey: marginCheckKey(typeKey ?? "", printer ?? "", tray),
    queryFn: () => apiFetch<MarginCheck>(`/api/v1/sheets/margin-check${queryString({ type: typeKey, printer, tray })}`),
    enabled: !!typeKey && !!printer,
  });

/**
 * What a sheet write changes besides the sheet itself: the lists and the type's usage. The sheet's
 * own key is not invalidated: the writes that answer with the sheet put it into the cache.
 */
function refreshAfterWrite(client: QueryClient) {
  void client.invalidateQueries({ queryKey: sheetsListKey });
  void client.invalidateQueries({ queryKey: typesListKey });
}

export function useCreateSheet() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: SheetCreate) => post<SheetCreated>("/api/v1/sheets", body),
    onSettled: () => {
      refreshAfterWrite(client);
      void client.invalidateQueries({ queryKey: ["jobs"] });
    },
  });
}

export function useDiscardSheet() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (code: string) => post<SheetRead>(`/api/v1/sheets/${encode(code)}/discard`),
    onSuccess: (sheet, code) => client.setQueryData(sheetKey(code), sheet),
    onSettled: () => refreshAfterWrite(client),
  });
}

/** A cell write answers with the whole sheet; it goes into the cache so the grid is current at once. */
function useCellsWrite<V extends { code: string }>(action: string, body: (v: V) => unknown) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (v: V) => post<SheetRead>(`/api/v1/sheets/${encode(v.code)}/cells/${action}`, body(v)),
    onSuccess: (sheet, v) => client.setQueryData(sheetKey(v.code), sheet),
    onSettled: () => refreshAfterWrite(client),
  });
}

export const useMarkCells = () =>
  useCellsWrite<{ code: string; cells: MarkedCellIn[] }>("mark", ({ cells }) => ({ cells }));
export const useUnmarkCells = () => useCellsWrite<{ code: string; cells: number[] }>("unmark", ({ cells }) => ({ cells }));
export const useResolveCells = () =>
  useCellsWrite<{ code: string; cells: number[]; outcome: "printed" | "not_printed" }>("resolve", ({ cells, outcome }) => ({
    cells,
    outcome,
  }));

/**
 * The plan for a print onto sheets, rendered by the server. The key sits outside `["printers", …]`
 * (see keys.ts); `sheet.updated` refreshes it only when a placement names that sheet.
 */
export const useSheetPreview = (printerId: string, request: SheetPrintRequest, enabled = true) =>
  useQuery({
    queryKey: sheetPreviewKey(printerId, request),
    queryFn: () => post<SheetPreview>(`/api/v1/print/${encode(printerId)}/sheet/preview`, request),
    enabled,
    retry: false,
    refetchOnWindowFocus: false,
    staleTime: 60_000,
    placeholderData: keepPreviousData,
  });

export function usePrintSheets(printerId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (request: SheetPrintRequest) => post<SheetPrintResponse>(`/api/v1/print/${encode(printerId)}/sheet`, request),
    onSuccess: (response) => void watchPrint({ kind: "sheet", printerId, jobIds: response.pages.map((p) => p.job_id) }),
    // A partial print (`print_interrupted`, or the failing page's own error) queued pages that keep printing: they get an entry too.
    onError: (error) => {
      const queued = queuedJobs(error);
      if (queued) watchPrint({ kind: "sheet", printerId, jobIds: queued });
    },
    // A partial print also queued pages, so this runs on failure too.
    onSettled: () => {
      refreshAfterWrite(client);
      void client.invalidateQueries({ queryKey: [SHEET_PREVIEW_KEY] });
      void client.invalidateQueries({ queryKey: ["jobs"] });
      void client.invalidateQueries({ queryKey: ["printers", printerId, "queue"] });
    },
  });
}
