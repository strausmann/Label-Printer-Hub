import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../../api/client";
import type { components } from "../../api/schema.gen";
import { submitBatch, type CartItem, type ContentType, type LookupApp } from "./cart";

export type LookupResult = components["schemas"]["LookupResult"];

/** A data URL has no lifetime to manage (an object URL would need revoking at the right moment). */
async function toDataUrl(blob: Blob): Promise<string> {
  const bytes = new Uint8Array(await blob.arrayBuffer());
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return `data:${blob.type || "image/png"};base64,${btoa(binary)}`;
}

export const lookupKey = (app: string, id: string) => ["lookup", app, id] as const;

export const useLookup = (app: LookupApp, id: string) =>
  useQuery({
    queryKey: lookupKey(app, id),
    queryFn: () => apiFetch<LookupResult>(`/api/lookup/${app}/${encodeURIComponent(id)}`),
    retry: false,
  });

const secondaryOf = (item: LookupResult): string[] => {
  const s = item.extra?.secondary;
  return Array.isArray(s) ? s.filter((x): x is string => typeof x === "string") : [];
};

/**
 * The label as a PNG, drawn from what the lookup returned. The print itself looks the item
 * up again on the server, so the preview is a close picture, not a promise.
 */
export function usePreviewImage(item: LookupResult, contentType: ContentType, tapeMm: number, enabled = true) {
  const query = useQuery({
    queryKey: ["preview", item.app, item.id, item.name, item.url, contentType, tapeMm],
    queryFn: () =>
      apiFetch<Blob>("/api/render/preview", {
        method: "POST",
        as: "blob",
        json: {
          content_type: contentType,
          tape_mm: tapeMm,
          data: { title: item.name, primary_id: item.id, qr_payload: item.url, secondary: secondaryOf(item) },
        },
      }).then(toDataUrl),
    retry: false,
    staleTime: 60_000,
    enabled,
  });
  return { url: query.data ?? null, isPending: query.isPending, isError: query.isError };
}

/** Print one item now: a batch of one. */
export function usePrintNow() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ printerKey, item }: { printerKey: string; item: CartItem }) => submitBatch(printerKey, [item]),
    onSettled: () => void client.invalidateQueries({ queryKey: ["jobs"] }),
  });
}
