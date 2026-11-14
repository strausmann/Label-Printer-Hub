// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

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

/** One sidebar entry per configured integration; the ones not set up are not listed (see `useConfiguredIntegrations`). */
export function IntegrationNavEntries({ integrations }: { integrations: IntegrationState[] }) {
  const appName = useAppName();
  return integrations.map(({ app }) => (
    <li key={app}>
      <Link
        to="/integrations/$app"
        params={{ app }}
        className={`${ROW} text-ink-2 hover:text-ink data-[status=active]:bg-sunken data-[status=active]:font-bold data-[status=active]:text-ink`}
      >
        {INTEGRATION_ICON[app]}
        <span>{appName(app)}</span>
      </Link>
    </li>
  ));
}
