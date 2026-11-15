// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useLingui } from "@lingui/react/macro";
import { useInfo } from "../../app/session";
import { Row } from "../Row";

/** Version and revision of the running build; the same two rows on the System and About pages. */
export function BuildRows() {
  const { t } = useLingui();
  const info = useInfo().data;
  // The image reports the literal "unknown" when it was built without a revision.
  const revision = info === undefined ? "…" : info.revision === "unknown" || info.revision === "" ? t`unknown` : info.revision;
  return (
    <>
      <Row label={t`Version`}>
        <span className="font-mono">{info?.version ?? "…"}</span>
      </Row>
      <Row label={t`Revision`}>
        <span className="font-mono">{revision}</span>
      </Row>
    </>
  );
}
