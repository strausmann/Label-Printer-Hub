import { useLingui } from "@lingui/react/macro";
import { Link } from "@tanstack/react-router";
import type { ReactNode } from "react";
import { useAppName } from "../features/lookup/apps";
import type { LookupApp } from "../features/lookup/cart";
import type { IntegrationState } from "../features/integrations/api";
import { AssetIcon, ProductIcon, SpoolIcon } from "./icons";

export const INTEGRATION_ICON: Record<LookupApp, ReactNode> = {
  snipeit: <AssetIcon />,
  grocy: <ProductIcon />,
  spoolman: <SpoolIcon />,
};

const ROW = "press flex h-10 items-center gap-3 rounded-r2 px-3 transition-colors duration-150 hover:bg-sunken";

/**
 * One sidebar entry per integration `/api/info` lists. A configured one opens its start page;
 * one that is not set up is muted and, for the admins who are given it, leads to the settings.
 */
export function IntegrationNavEntries({ integrations }: { integrations: IntegrationState[] }) {
  const { t } = useLingui();
  const appName = useAppName();
  return integrations.map(({ app, configured }) => (
    <li key={app}>
      {configured ? (
        <Link
          to="/integrations/$app"
          params={{ app }}
          className={`${ROW} text-ink-2 hover:text-ink data-[status=active]:bg-sunken data-[status=active]:font-bold data-[status=active]:text-ink`}
        >
          {INTEGRATION_ICON[app]}
          <span>{appName(app)}</span>
        </Link>
      ) : (
        <Link to="/settings/$" params={{ _splat: "integrations" }} className={`${ROW} text-ink-3 hover:text-ink-2`}>
          {INTEGRATION_ICON[app]}
          <span>{appName(app)}</span>
          <span className="ml-auto text-small">{t`Not set up`}</span>
        </Link>
      )}
    </li>
  ));
}
