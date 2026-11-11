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
    entries: [{ id: "settings", to: "/settings", icon: <SettingsIcon /> }],
  },
];

/** The groups with their hidden entries removed; a group left empty disappears. */
export function visibleGroups(isOn: (feature: string) => boolean): NavGroup[] {
  return NAV_GROUPS.map((group) => ({
    ...group,
    entries: group.entries.filter((entry) => entry.feature === undefined || isOn(entry.feature)),
  })).filter((group) => group.entries.length > 0);
}
