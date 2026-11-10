import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../../api/client";
import type { components } from "../../api/schema.gen";
import { queryString } from "../../api/queryString";
import { useEffect, useRef } from "react";
import { releaseClaimPending, watchPrint } from "../jobs/printWatch";
import { calibrationKey, capabilitiesKey } from "../sheets/keys";

export { calibrationKey, capabilitiesKey } from "../sheets/keys";

type Schemas = components["schemas"];
export type CalibrationRead = Schemas["CalibrationRead"];
export type CalibrationPut = Schemas["CalibrationPut"];
export type FitRequest = Schemas["FitRequest"];
export type FitResponse = Schemas["FitResponse"];
export type CalibrationPageRequest = Schemas["PageRequest"];
export type Capabilities = Schemas["Capabilities"];

const encode = encodeURIComponent;
const trayPath = (printerId: string, tray: string) => `/api/v1/printers/${encode(printerId)}/calibration/${encode(tray)}`;

/** One calibration per tray of the printer. Nested under `["printers", id]`, so a printer event refreshes it. */
export const useCalibration = (printerId: string) =>
  useQuery({
    queryKey: calibrationKey(printerId),
    queryFn: () => apiFetch<CalibrationRead[]>(`/api/v1/printers/${encode(printerId)}/calibration`),
  });

export function useSaveCalibration(printerId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ tray, values }: { tray: string; values: CalibrationPut }) =>
      apiFetch<CalibrationRead>(trayPath(printerId, tray), { method: "PUT", json: values }),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: calibrationKey(printerId) });
      void client.invalidateQueries({ queryKey: capabilitiesKey(printerId) });
    },
  });
}

/** Back to no correction for one tray (the stored values are deleted; no calibration means identity). */
export function useResetCalibration(printerId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ tray }: { tray: string }) => apiFetch<null>(trayPath(printerId, tray), { method: "DELETE" }),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: calibrationKey(printerId) });
      void client.invalidateQueries({ queryKey: capabilitiesKey(printerId) });
    },
  });
}

/** Turns measured readings into correction values; nothing is stored until they are saved. */
export const useFit = (printerId: string) =>
  useMutation({
    mutationFn: ({ tray, request }: { tray: string; request: FitRequest }) =>
      apiFetch<FitResponse>(`${trayPath(printerId, tray)}/fit`, { method: "POST", json: request }),
  });

/** Prints the calibration page (`{job_id}` back). */
export function usePrintCalibrationPage(printerId: string) {
  const client = useQueryClient();
  // The print is registered "claim pending" (the page's status line is about to claim it, so the stack does not
  // announce it twice). That only holds while this page is there: after it went away, nobody will claim it.
  const mounted = useRef(false);
  const registered = useRef<string[]>([]);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      registered.current.forEach(releaseClaimPending);
      registered.current = [];
    };
  }, []);
  return useMutation({
    mutationFn: ({ tray, request }: { tray: string; request: CalibrationPageRequest }) =>
      apiFetch<Schemas["PageJobAccepted"]>(`${trayPath(printerId, tray)}/page`, { method: "POST", json: request }),
    onSuccess: (accepted) => {
      registered.current.push(accepted.job_id);
      void watchPrint({ kind: "calibration", printerId, jobIds: [accepted.job_id], claimPending: mounted.current });
    },
    onSettled: () => void client.invalidateQueries({ queryKey: ["jobs"] }),
  });
}

/** The address of the calibration page as a PDF (a download, so a plain link, not a fetch). */
export function calibrationPdfUrl(
  printerId: string,
  tray: string,
  options: { type: string; version?: number | null; corrected: boolean },
): string {
  return `${trayPath(printerId, tray)}/page/pdf${queryString({
    type: options.type,
    version: options.version,
    corrected: options.corrected,
  })}`;
}

export const useCapabilities = (printerId: string) =>
  useQuery({
    queryKey: capabilitiesKey(printerId),
    queryFn: () => apiFetch<Capabilities>(`/api/v1/printers/${encode(printerId)}/capabilities`),
    // A screen that has not chosen a printer yet passes "" and asks for nothing.
    enabled: printerId !== "",
  });
