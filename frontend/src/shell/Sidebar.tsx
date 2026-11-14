// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useLingui } from "@lingui/react/macro";
import { Link } from "@tanstack/react-router";
import { useInfo } from "../app/session";
import { IntegrationNavEntries } from "./IntegrationNav";
import { NAV_GROUPS, visibleGroups, type NavGroup } from "./features";
import { useNavLabels } from "./labels";
import { StatusBadge } from "./StatusBadge";
import { SourceLink } from "../features/about/SourceLink";
import { useConfiguredIntegrations } from "../features/integrations/api";
import { messages } from "../i18n/messages";

/** Desktop navigation (>= 1024 px): groups as in spec 5.3, hidden entries removed. */
export function Sidebar() {
  const { t, i18n } = useLingui();
  const info = useInfo();
  const labels = useNavLabels();
  const integrations = useConfiguredIntegrations();
  const shown = visibleGroups((feature) => info.data?.features[feature] ?? false);
  // The integrations come from `/api/v1/info`, not from `NAV_GROUPS`: the group exists as soon as one is visible.
  const groups = NAV_GROUPS.flatMap((g): NavGroup[] => {
    const entry = shown.find((v) => v.id === g.id);
    if (entry) return [entry];
    return g.id === "integrations" && integrations.length > 0 ? [{ ...g, entries: [] }] : [];
  });

  const status = info.data
    ? { state: "ok" as const, label: t`Connected · v${info.data.version}` }
    : info.isError
      ? { state: "bad" as const, label: t`Server unreachable` }
      : { state: "idle" as const, label: t`Connecting…` };

  return (
    <aside className="sticky top-0 hidden h-dvh w-64 shrink-0 flex-col border-r border-line bg-surface lg:flex">
      <div className="px-6 pt-6 pb-4">
        <Link to="/" className="press flex items-center gap-3 text-section font-bold text-ink">
          {/* One mark per colour scheme (index.css shows the matching one); the name carries the meaning. */}
          <img src="/brand/mark.svg" alt="" width={32} height={32} className="brand-light size-8 shrink-0" />
          <img src="/brand/mark-dark.svg" alt="" width={32} height={32} className="brand-dark size-8 shrink-0" />
          <span className="min-w-0 [overflow-wrap:anywhere]">{info.data?.display_name ?? i18n._(messages.appName)}</span>
        </Link>
      </div>
      <nav aria-label={t`Main`} className="flex-1 overflow-y-auto px-3 pb-4">
        {groups.map((group) => {
          const heading = labels.group[group.id];
          const headingId = `nav-group-${group.id}`;
          return (
            <div key={group.id} className={heading ? "mt-6" : undefined}>
              {heading ? (
                <p id={headingId} className="px-3 pb-1 text-small font-bold text-ink-3">
                  {heading}
                </p>
              ) : null}
              <ul aria-labelledby={heading ? headingId : undefined} className="flex flex-col gap-0.5">
                {group.id === "integrations" && <IntegrationNavEntries integrations={integrations} />}
                {group.entries.map((entry) => (
                  <li key={entry.id}>
                    <Link
                      to={entry.to}
                      activeOptions={{ exact: entry.to === "/" || entry.to === "/sheets" }}
                      className="press flex h-10 items-center gap-3 rounded-r2 px-3 text-ink-2 transition-colors duration-150 hover:bg-sunken hover:text-ink data-[status=active]:bg-sunken data-[status=active]:font-bold data-[status=active]:text-ink"
                    >
                      {entry.icon}
                      <span>{labels.entry[entry.id]}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
      </nav>
      <div className="flex flex-col gap-3 border-t border-line px-6 py-4">
        <StatusBadge state={status.state} label={status.label} />
        <p className="flex flex-wrap gap-x-4 gap-y-1 text-small">
          <Link to="/about" className="press text-ink-2 underline underline-offset-2 hover:text-ink">
            {t({ message: "About and licences", context: "link to the about page" })}
          </Link>
          <SourceLink className="press text-ink-2 underline underline-offset-2 hover:text-ink" />
        </p>
      </div>
    </aside>
  );
}
