import { useLingui } from "@lingui/react/macro";
import { Link } from "@tanstack/react-router";
import { INTEGRATION_ICON } from "../../shell/IntegrationNav";
import { StatusBadge } from "../../shell/StatusBadge";
import { useAppName } from "../lookup/apps";
import { PANEL, SECTION_HEADING } from "../ui";
import { useVisibleIntegrations } from "./api";

const TILE = `${PANEL} flex min-h-20 flex-col justify-between gap-2`;

/**
 * Phone only: there is no sidebar, so the Overview carries the way into each integration.
 * Same visibility rule as the sidebar: configured ones, plus the unconfigured ones for an admin.
 */
export function IntegrationTiles() {
  const { t } = useLingui();
  const appName = useAppName();
  const integrations = useVisibleIntegrations();
  if (integrations.length === 0) return null;
  return (
    <section aria-labelledby="integrations-h" className="flex flex-col gap-3 lg:hidden">
      <h2 id="integrations-h" className={SECTION_HEADING}>{t`Integrations`}</h2>
      <ul className="grid grid-cols-2 gap-3">
        {integrations.map(({ app, configured }) => {
          const name = appName(app);
          return (
            <li key={app} className={configured ? undefined : "col-span-2"}>
              {configured ? (
                <Link to="/integrations/$app" params={{ app }} className={`${TILE} press block`}>
                  <span className="flex items-center gap-2 font-bold">
                    {INTEGRATION_ICON[app]}
                    {name}
                  </span>
                  <StatusBadge state="ok" label={t`Connected`} />
                </Link>
              ) : (
                <div className={`${TILE} text-ink-2`}>
                  <span className="flex items-center gap-2 font-bold text-ink">
                    {INTEGRATION_ICON[app]}
                    {name}
                  </span>
                  <span className="flex items-center gap-2 text-small">
                    {t`Not set up`} ·
                    <Link
                      to="/settings/integrations"
                      aria-label={t`Set up ${name}`}
                      className="inline-flex h-11 items-center text-link underline underline-offset-2"
                    >
                      {t`Set up`}
                    </Link>
                  </span>
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
