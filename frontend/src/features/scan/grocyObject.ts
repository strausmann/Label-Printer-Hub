// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../../api/client";
import type { components } from "../../api/schema.gen";

export type GrocyBattery = components["schemas"]["GrocyBatteryResult"];
export type GrocyChore = components["schemas"]["GrocyChoreResult"];

/** The facts of a scanned battery (`b`) or chore (`c`), read through the hub (the key stays on the server). */
export function useGrocyObject(entity: "b" | "c", id: string) {
  const path = entity === "b" ? "batteries" : "chores";
  return useQuery({
    // Not under "lookup": that prefix is where the Grocy address is read from, and these answers carry none of a product's.
    queryKey: ["grocy-object", entity, id] as const,
    queryFn: () => apiFetch<GrocyBattery | GrocyChore>(`/api/v1/lookup/grocy/${path}/${encodeURIComponent(id)}`),
    retry: false,
  });
}
