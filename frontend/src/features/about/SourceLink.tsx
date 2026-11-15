// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useLingui } from "@lingui/react/macro";
import { useInfo } from "../../app/session";

export const SOURCE_LINK_CLASS =
  "press inline-flex min-h-11 items-center text-link underline underline-offset-2 focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-link";

/**
 * Link to the source of the running build (AGPL section 13, D20). Renders nothing until
 * `/api/v1/info` has answered, so there is never a link with an empty target.
 */
export function SourceLink({ className = SOURCE_LINK_CLASS }: { className?: string }) {
  const { t } = useLingui();
  const sourceUrl = useInfo().data?.source_url;
  if (!sourceUrl) return null;
  return (
    // D20
    <a href={sourceUrl} target="_blank" rel="noopener noreferrer" className={className}>
      {t({ message: "Source code", context: "link to the source of the running version" })}
    </a>
  );
}
