// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useLingui } from "@lingui/react/macro";
import { Link } from "@tanstack/react-router";
import { INTEGRATION_ICON } from "../../shell/IntegrationNav";
import { StatusBadge } from "../../shell/StatusBadge";
import { useAppName } from "../lookup/apps";
import { PANEL, SECTION_HEADING } from "../ui";
import { useConfiguredIntegrations } from "./api";

const TILE = `${PANEL} flex min-h-20 flex-col justify-between gap-2`;

/**
 * Phone only: there is no sidebar, so the Overview carries the way into each integration.
 * Same rule as the sidebar: only what is set up. Setting up is done in Settings > Integrations;
 * a tile that says "not set up" is a dead end in daily use, so none is shown, for admins either.
 */
export function IntegrationTiles() {
  const { t } = useLingui();
  const appName = useAppName();
  const integrations = useConfiguredIntegrations();
  if (integrations.length === 0) return null;
  return (
    <section aria-labelledby="integrations-h" className="flex flex-col gap-3 lg:hidden">
      <h2 id="integrations-h" className={SECTION_HEADING}>{t`Integrations`}</h2>
      <ul className="grid grid-cols-2 gap-3">
        {integrations.map(({ app }) => (
          <li key={app}>
            <Link to="/integrations/$app" params={{ app }} className={`${TILE} press block`}>
              <span className="flex items-center gap-2 font-bold">
                {INTEGRATION_ICON[app]}
                {appName(app)}
              </span>
              <StatusBadge state="ok" label={t`Configured`} />
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
