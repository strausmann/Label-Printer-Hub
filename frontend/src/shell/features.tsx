// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import type { ReactNode } from "react";
import {
  ArchiveIcon,
  CalibrationIcon,
  DocumentIcon,
  JobsIcon,
  LinkIcon,
  OverviewIcon,
  PrintersIcon,
  SettingsIcon,
  SheetsIcon,
} from "./icons";
import type { IntegrationState } from "../features/integrations/api";

/** Route paths the navigation links to (all registered in `app/router.tsx`). */
export type NavPath =
  | "/"
  | "/printers"
  | "/jobs"
  | "/sheets"
  | "/sheets/archive"
  | "/calibration"
  | "/asn"
  | "/kept"
  | "/settings";

export interface NavEntry {
  id: string;
  to: NavPath;
  icon: ReactNode;
  /** Hidden until `GET /api/v1/info` reports this feature as shipped (spec 5.3). */
  feature?: string;
  /** Shown to admin sessions only (the settings routes are admin-only). */
  admin?: true;
}

export interface NavGroup {
  id: "main" | "material" | "integrations" | "system";
  entries: NavEntry[];
}

/** The sidebar, in the order of spec 5.3. Labels live in `Sidebar.tsx` (translated there). */
export const NAV_GROUPS: NavGroup[] = [
  {
    id: "main",
    entries: [
      { id: "overview", to: "/", icon: <OverviewIcon /> },
      { id: "printers", to: "/printers", icon: <PrintersIcon /> },
      { id: "jobs", to: "/jobs", icon: <JobsIcon /> },
    ],
  },
  {
    id: "material",
    entries: [
      { id: "sheets", to: "/sheets", icon: <SheetsIcon />, feature: "sheets" },
      { id: "sheet-archive", to: "/sheets/archive", icon: <ArchiveIcon />, feature: "sheets" },
      { id: "calibration", to: "/calibration", icon: <CalibrationIcon />, feature: "calibration" },
    ],
  },
  {
    id: "integrations",
    entries: [
      { id: "asn", to: "/asn", icon: <DocumentIcon />, feature: "asn" },
      { id: "kept", to: "/kept", icon: <LinkIcon />, feature: "kept" },
    ],
  },
  {
    id: "system",
    entries: [{ id: "settings", to: "/settings", icon: <SettingsIcon />, admin: true }],
  },
];

/** The groups with their hidden entries removed; a group left empty disappears. */
export function visibleGroups(isOn: (feature: string) => boolean, opts: { admin: boolean }): NavGroup[] {
  return NAV_GROUPS.map((group) => ({
    ...group,
    entries: group.entries.filter(
      (entry) => (entry.feature === undefined || isOn(entry.feature)) && (!entry.admin || opts.admin),
    ),
  })).filter((group) => group.entries.length > 0);
}

/**
 * The navigation as the sidebar and the phone menu list it. The integrations come from `/api/v1/info`, not from
 * `NAV_GROUPS`: that group is present as soon as it has entries or one integration is configured.
 */
export function navGroups(input: {
  isOn: (feature: string) => boolean;
  admin: boolean;
  integrations: IntegrationState[];
}): NavGroup[] {
  const shown = visibleGroups(input.isOn, { admin: input.admin });
  return NAV_GROUPS.flatMap((g): NavGroup[] => {
    const entry = shown.find((v) => v.id === g.id);
    if (entry) return [entry];
    return g.id === "integrations" && input.integrations.length > 0 ? [{ ...g, entries: [] }] : [];
  });
}

/** Route paths of the settings sections (all registered in `app/router.tsx`). */
export type SettingsPath =
  | "/settings"
  | "/settings/printers"
  | "/settings/integrations"
  | "/settings/access"
  | "/settings/jobs"
  | "/settings/system";

/** The settings sections in the order of the settings navigation; labels in `useNavLabels().sections`. */
export const SETTINGS_SECTIONS: {
  id: "general" | "printers" | "integrations" | "access" | "jobs" | "system";
  to: SettingsPath;
}[] = [
  { id: "general", to: "/settings" },
  { id: "printers", to: "/settings/printers" },
  { id: "integrations", to: "/settings/integrations" },
  { id: "access", to: "/settings/access" },
  { id: "jobs", to: "/settings/jobs" },
  { id: "system", to: "/settings/system" },
];
