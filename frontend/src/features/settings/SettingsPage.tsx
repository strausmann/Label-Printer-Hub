// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useLingui } from "@lingui/react/macro";
import { Link, Outlet } from "@tanstack/react-router";
import { useSession } from "../../app/session";
import { SETTINGS_SECTIONS } from "../../shell/features";
import { useNavLabels } from "../../shell/labels";

const NAV_LINK =
  "press inline-flex h-11 shrink-0 items-center whitespace-nowrap rounded-r2 px-4 font-bold text-ink-2 transition-colors duration-150 hover:bg-sunken hover:text-ink data-[status=active]:bg-accent-soft data-[status=active]:text-ink focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-link";

/** Settings: admin sessions only (the section navigation and a page for the rest). */
export function SettingsLayout() {
  const { t } = useLingui();
  const session = useSession();
  const labels = useNavLabels();

  if (session.scope !== "admin") {
    return (
      <div className="flex max-w-prose flex-col gap-2">
        <h1 className="text-title font-bold">{t`You need an admin key`}</h1>
        <p className="text-ink-2">{t`Settings can only be changed with an admin key. Sign in with one, or ask an admin.`}</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-title font-bold">{t`Settings`}</h1>
      <div className="flex flex-col gap-8 lg:flex-row lg:items-start">
        <nav aria-label={t`Settings sections`} className="-mx-4 overflow-x-auto px-4 lg:mx-0 lg:w-56 lg:shrink-0 lg:overflow-visible lg:px-0">
          <ul className="flex gap-1 lg:flex-col">
            {SETTINGS_SECTIONS.map((section) => (
              <li key={section.to} className="lg:w-full">
                <Link to={section.to} activeOptions={{ exact: section.to === "/settings" }} className={`${NAV_LINK} lg:w-full`}>
                  {labels.sections[section.id]}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
        <div className="min-w-0 flex-1">
          <Outlet />
        </div>
      </div>
    </div>
  );
}
