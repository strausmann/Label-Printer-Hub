// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useQueryClient } from "@tanstack/react-query";
import { safeHref } from "../lookup/apps";
import type { LookupApp } from "../lookup/cart";
import { baseUrlOf } from "./baseUrl";

/**
 * The app's own address, known only once an item of it was shown in this session: the hub's
 * `/api/v1/info` carries no URL on purpose, a lookup result does carry the deep link.
 */
export function useKnownBase(app: LookupApp): string | null {
  const queryClient = useQueryClient();
  for (const [, result] of queryClient.getQueriesData<{ url?: string | null }>({ queryKey: ["lookup", app] })) {
    const href = safeHref(result?.url);
    const base = href ? baseUrlOf(app, href) : null;
    if (base) return base;
  }
  return null;
}
