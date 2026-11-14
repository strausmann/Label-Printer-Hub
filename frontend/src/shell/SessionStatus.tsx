// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useLingui } from "@lingui/react/macro";
import { useSession } from "../app/session";
import { StatusBadge } from "./StatusBadge";

/** Shown while the server could not confirm the session; changes wait until it answers. */
export function SessionStatus() {
  const { t } = useLingui();
  const { unverified } = useSession();
  if (!unverified) return null;
  return (
    <div role="status" className="mb-4">
      <StatusBadge state="warn" label={t`Checking your session…`} />
    </div>
  );
}
