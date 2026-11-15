// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useLingui } from "@lingui/react/macro";
import { useInfo } from "../../app/session";
import { PANEL, SECONDARY_BUTTON } from "../ui";
import { Row } from "../Row";
import { DependencyLicences } from "./DependencyLicences";
import { BuildRows } from "./BuildRows";
import { Section } from "../settings/sections";
import { SourceLink } from "./SourceLink";

/** Shipped by the image build (A5). */
export const PROJECT_LICENCE_TEXT_URL = "/licenses/agpl-3.0.txt";
export const AGPL_INFO_URL = "https://www.gnu.org/licenses/agpl-3.0.html";

const BUTTON = `${SECONDARY_BUTTON} no-underline`;

/** Licence, version and the source of exactly this build, for every signed-in user (AGPL section 13). */
export function AboutPage() {
  const { t } = useLingui();
  const info = useInfo().data;

  return (
    <div className="flex flex-col gap-10">
      <h1 className="text-title font-bold">{t({ message: "About", context: "page title" })}</h1>

      <Section
        title={t({ message: "Licence", context: "heading" })}
        intro={t`This hub is free software under the GNU Affero General Public License, version 3 or later. You can get the source of exactly this version at any time.`}
      >
        <dl className={`${PANEL} max-w-xl`}>
          <Row label={t({ message: "Licence", context: "field label" })}>
            <span className="font-mono">{info?.license ?? "…"}</span>
          </Row>
          <BuildRows />
        </dl>
        <div className="flex flex-wrap gap-3">
          <SourceLink className={BUTTON} />
          <a href={PROJECT_LICENCE_TEXT_URL} target="_blank" rel="noopener noreferrer" className={BUTTON}>
            {t({ message: "Read the licence", context: "action" })}
          </a>
          <a href={AGPL_INFO_URL} target="_blank" rel="noopener noreferrer" className={BUTTON}>
            {t({ message: "About the GNU AGPL", context: "link" })}
          </a>
        </div>
      </Section>

      <div data-section="dependencies">
        <DependencyLicences />
      </div>
    </div>
  );
}
