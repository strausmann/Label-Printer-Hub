// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useInfo, useSession } from "../../app/session";
import { LOOKUP_APPS } from "../lookup/apps";
import type { LookupApp } from "../lookup/cart";

export interface IntegrationState {
  app: LookupApp;
  configured: boolean;
}

/** Only an admin can change the settings, so only an admin is sent there. */
export const useIsAdmin = (): boolean => useSession().scope === "admin";

/** The state of each integration as `/api/v1/info` reports it, in the navigation's order. */
export function useIntegrationStates(): IntegrationState[] {
  const info = useInfo().data;
  if (!info) return [];
  return LOOKUP_APPS.flatMap((app) => {
    const found = info.integrations.find((i) => i.name === app);
    return found ? [{ app, configured: found.configured }] : [];
  });
}

/**
 * What to show in the navigation: the configured integrations only. One that is not set up is
 * configured in Settings > Integrations, which lists all of them; the navigation offers no dead ends.
 */
export function useConfiguredIntegrations(): IntegrationState[] {
  return useIntegrationStates().filter((i) => i.configured);
}
