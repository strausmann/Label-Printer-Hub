import { useInfo, useSession } from "../../app/session";
import { LOOKUP_APPS } from "../lookup/apps";
import type { LookupApp } from "../lookup/cart";

export interface IntegrationState {
  app: LookupApp;
  configured: boolean;
}

/** Only an admin can change the settings, so only an admin is sent there. */
export const useIsAdmin = (): boolean => useSession().scope === "admin";

/** The state of each integration as `/api/info` reports it, in the navigation's order. */
export function useIntegrationStates(): IntegrationState[] {
  const info = useInfo().data;
  if (!info) return [];
  return LOOKUP_APPS.flatMap((app) => {
    const found = info.integrations.find((i) => i.name === app);
    return found ? [{ app, configured: found.configured }] : [];
  });
}

/**
 * What to show in the navigation: every configured integration, plus (for an admin) the ones
 * still to be set up. Someone who cannot fix it is not shown a dead end.
 */
export function useVisibleIntegrations(): IntegrationState[] {
  const admin = useIsAdmin();
  return useIntegrationStates().filter((i) => i.configured || admin);
}
