import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, apiFetch } from "../../api/client";
import type { components } from "../../api/schema.gen";
import { INFO_KEY } from "../../app/session";
import { printersKey } from "../printers/api";

export type SettingView = components["schemas"]["SettingView"];
export type AdminPrinter = components["schemas"]["app__api__routes__admin_printers_api__PrinterRead"];
export type PrinterCreate = components["schemas"]["PrinterCreatePayload"];
export type PrinterUpdate = components["schemas"]["PrinterUpdatePayload"];
export type ApiKey = components["schemas"]["ApiKeyRead"];
export type ApiKeyCreated = components["schemas"]["ApiKeyCreateResponse"];
export type IntegrationTestResult = components["schemas"]["IntegrationTestResult"];
export type LogEntry = components["schemas"]["LogEntry"];

export const settingsKey = ["settings"] as const;
export const adminPrintersKey = ["admin", "printers"] as const;
export const apiKeysKey = ["admin", "api-keys"] as const;

export const useSettings = () =>
  useQuery({ queryKey: settingsKey, queryFn: () => apiFetch<SettingView[]>("/api/v1/settings") });

/** PUT only what changed. The answer is the fresh list; the sidebar's integration entries follow `/api/info`. */
export function useSaveSettings() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (values: Record<string, unknown>) =>
      apiFetch<SettingView[]>("/api/v1/settings", { method: "PUT", json: { values } }),
    onSuccess: (fresh) => {
      client.setQueryData(settingsKey, fresh);
      void client.invalidateQueries({ queryKey: INFO_KEY });
    },
  });
}

export const useTestIntegration = (name: string) =>
  useMutation({
    mutationFn: (values: Record<string, unknown>) =>
      apiFetch<IntegrationTestResult>(`/api/v1/settings/integrations/${name}/test`, { method: "POST", json: { values } }),
  });

export const useAdminPrinters = () =>
  useQuery({
    queryKey: adminPrintersKey,
    queryFn: () => apiFetch<AdminPrinter[]>("/api/v1/admin/printers?include_disabled=true"),
  });

/** Create, update or switch a printer; the shell's printer lists refresh too. */
export function usePrinterAdmin() {
  const client = useQueryClient();
  const done = () => {
    void client.invalidateQueries({ queryKey: adminPrintersKey });
    void client.invalidateQueries({ queryKey: printersKey });
  };
  return {
    create: useMutation({
      mutationFn: (body: PrinterCreate) => apiFetch<AdminPrinter>("/api/v1/admin/printers", { method: "POST", json: body }),
      onSuccess: done,
    }),
    update: useMutation({
      mutationFn: ({ slug, body }: { slug: string; body: PrinterUpdate }) =>
        apiFetch<AdminPrinter>(`/api/v1/admin/printers/${slug}`, { method: "PUT", json: body }),
      onSuccess: done,
    }),
    toggle: useMutation({
      mutationFn: ({ slug, enable }: { slug: string; enable: boolean }) =>
        apiFetch<AdminPrinter>(`/api/v1/admin/printers/${slug}/${enable ? "enable" : "disable"}`, { method: "POST" }),
      onSuccess: done,
    }),
  };
}

export const useApiKeys = () =>
  useQuery({ queryKey: apiKeysKey, queryFn: () => apiFetch<ApiKey[]>("/api/admin/api-keys") });

export function useApiKeyAdmin() {
  const client = useQueryClient();
  const done = () => client.invalidateQueries({ queryKey: apiKeysKey });
  return {
    create: useMutation({
      mutationFn: (body: { name: string; scopes: string[] }) =>
        apiFetch<ApiKeyCreated>("/api/admin/api-keys", { method: "POST", json: body }),
      onSuccess: done,
    }),
    revoke: useMutation({
      mutationFn: (id: string) => apiFetch<void>(`/api/admin/api-keys/${id}`, { method: "DELETE" }),
      onSuccess: done,
    }),
  };
}

export const useLogs = () =>
  useQuery({ queryKey: ["system", "logs"], queryFn: () => apiFetch<LogEntry[]>("/api/v1/system/logs?limit=200") });

export interface Health {
  status: string;
  version: string;
  revision: string;
  build_date: string;
}
export interface Readiness {
  status: "ready" | "degraded" | "not-ready";
  checks: Record<string, { status: "ok" | "fail" | "skipped" | "stale"; detail?: string | null }>;
}

export const useHealth = () =>
  useQuery({ queryKey: ["system", "healthz"], queryFn: () => apiFetch<Health>("/healthz"), retry: false });

/** `/readiness` answers 503 with a full body when not ready; that body is the answer, not an error. */
export const useReadiness = () =>
  useQuery({
    queryKey: ["system", "readiness"],
    retry: false,
    queryFn: async (): Promise<Readiness> => {
      let response: Response;
      try {
        response = await fetch("/readiness", { credentials: "same-origin", headers: { Accept: "application/json" } });
      } catch {
        throw new ApiError(0, "network_error", "Network error");
      }
      if (response.status !== 200 && response.status !== 503) throw new ApiError(response.status, null, `HTTP ${response.status}`);
      return (await response.json()) as Readiness;
    },
  });
