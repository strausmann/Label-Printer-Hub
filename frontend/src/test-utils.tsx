// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { createMemoryHistory } from "@tanstack/react-router";
import type { QueryClient } from "@tanstack/react-query";
import { act, render } from "@testing-library/react";
import { App } from "./App";
import { createQueryClient } from "./app/queryClient";
import { createAppRouter } from "./app/router";
import { INFO_KEY, SESSION_KEY, type InfoData, type SessionData } from "./app/session";
import { initI18n } from "./i18n";

export const INFO: InfoData = {
  version: "0.0.0-test",
  revision: "test",
  build_date: "1970-01-01T00:00:00Z",
  license: "AGPL-3.0-or-later",
  source_url: "https://github.com/strausmann/labelyard",
  default_language: "en",
  display_name: "Labelyard",
  auth: { sso_configured: false, bootstrap_open: false },
  features: { jobs: true, lookup: true, scan: true, sheets: false, calibration: false, asn: false, kept: false },
  integrations: [
    { name: "snipeit", configured: true },
    { name: "grocy", configured: true },
    { name: "spoolman", configured: true },
  ],
};

export const SIGNED_IN: SessionData = {
  signed_in: true,
  scope: "admin",
  source: "api-key",
  user: null,
  bootstrap: false,
  csrf_token: "csrf-test",
};

export const SIGNED_OUT: SessionData = { signed_in: false, bootstrap: false };

export interface RenderOptions {
  path?: string;
  info?: Partial<InfoData> & { features?: Record<string, boolean> };
  session?: SessionData | null;
  /** UI language; the default is English, like a fresh install. */
  language?: "en" | "de";
}

/** Renders the whole app on an in-memory history with the info and session cache seeded. */
export async function renderApp(options: RenderOptions = {}) {
  await initI18n(options.language ?? "en");
  const queryClient: QueryClient = createQueryClient();
  queryClient.setQueryData(INFO_KEY, { ...INFO, ...options.info, features: { ...INFO.features, ...options.info?.features } });
  if (options.session !== null) queryClient.setQueryData(SESSION_KEY, options.session ?? SIGNED_IN);
  const router = createAppRouter({ history: createMemoryHistory({ initialEntries: [options.path ?? "/"] }) });
  const utils = render(<App queryClient={queryClient} router={router} />);
  await act(async () => {
    await router.load();
  });
  return { ...utils, queryClient, router };
}
