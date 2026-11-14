// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useLingui } from "@lingui/react/macro";
import type { NavGroup } from "./features";

/** Translated labels of the navigation entries and group headings (sidebar and tab bar). */
export function useNavLabels() {
  const { t } = useLingui();
  const entry: Record<string, string> = {
    overview: t`Overview`,
    printers: t`Printers`,
    jobs: t`Jobs`,
    sheets: t`Sheets`,
    "sheet-archive": t`Sheet archive`,
    calibration: t`Calibration`,
    asn: t`Paperless ASN`,
    kept: t`Kept / Hangar / Grocy`,
    settings: t`Settings`,
    scan: t`Scan`,
  };
  const group: Record<NavGroup["id"], string | null> = {
    main: null,
    material: t`Material`,
    integrations: t`Integrations`,
    system: t`System`,
  };
  return { entry, group };
}
