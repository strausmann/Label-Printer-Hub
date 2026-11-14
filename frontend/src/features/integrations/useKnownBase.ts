// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { safeHref } from "../lookup/apps";
import type { LookupApp } from "../lookup/cart";
import { baseUrlOf } from "./baseUrl";

export const knownBaseKey = (app: LookupApp) => `lph.knownBase.${app}`;

/** A base address passes only as an http(s) origin with the app's path prefix; nothing else is trusted, stored or shown. */
function checkedBase(app: LookupApp, value: string | null | undefined): string | null {
  const href = safeHref(value);
  if (!href) return null;
  const base = baseUrlOf(app, `${href.replace(/\/+$/, "")}${SAMPLE_PATH[app]}`);
  return base && safeHref(base) ? base : null;
}

/** A deep link of each app, so a stored base can be run through the same reader as a lookup's link. */
const SAMPLE_PATH: Record<LookupApp, string> = { snipeit: "/hardware/1", grocy: "/product/1", spoolman: "/spool/show/1" };

function readStored(app: LookupApp): string | null {
  try {
    return checkedBase(app, localStorage.getItem(knownBaseKey(app)));
  } catch {
    return null;
  }
}

function store(app: LookupApp, base: string): void {
  try {
    localStorage.setItem(knownBaseKey(app), base);
  } catch {
    /* no storage (private mode, blocked): the address is simply not remembered */
  }
}

/**
 * The app's own address. A lookup result carries the deep link (the hub's `/api/v1/info` carries no URL on purpose),
 * so it is known once an item was shown; the last one seen is remembered in this browser, so a reload or a fresh
 * start of the installed app still knows it. The stored value is checked again on every read.
 */
export function useKnownBase(app: LookupApp): string | null {
  const queryClient = useQueryClient();
  let fromCache: string | null = null;
  for (const [, result] of queryClient.getQueriesData<{ url?: string | null }>({ queryKey: ["lookup", app] })) {
    const href = safeHref(result?.url);
    fromCache = href ? baseUrlOf(app, href) : null;
    if (fromCache) break;
  }
  useEffect(() => {
    if (fromCache) store(app, fromCache);
  }, [app, fromCache]);
  return fromCache ?? readStored(app);
}
