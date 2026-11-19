// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useLingui } from "@lingui/react/macro";
import { useInfo } from "../app/session";
import { StatusBadge } from "./StatusBadge";

/** The connection status line with the running version; the sidebar and the phone menu show the same one. */
export function ConnectionStatus() {
  const { t } = useLingui();
  const info = useInfo();
  const status = info.data
    ? { state: "ok" as const, label: t`Connected · v${info.data.version}` }
    : info.isError
      ? { state: "bad" as const, label: t`Server unreachable` }
      : { state: "idle" as const, label: t`Connecting…` };
  return <StatusBadge state={status.state} label={status.label} />;
}
