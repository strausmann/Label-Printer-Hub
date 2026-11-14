// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useLingui } from "@lingui/react/macro";
import { getRouteApi, Link } from "@tanstack/react-router";
import { useKnownBase } from "../integrations/useKnownBase";
import { NotFoundPage } from "../../pages/placeholders";
import { PRIMARY_BUTTON, SECONDARY_BUTTON } from "../ui";

const route = getRouteApi("/grocycode/$entity/$id");

/**
 * Where a scanned battery or chore code lands. The hub has no battery or chore view of its own, so
 * the page says what was read and, when the Grocy address is known, links to the item in Grocy.
 */
export function GrocycodePage() {
  const { entity, id } = route.useParams();
  if ((entity !== "b" && entity !== "c") || !/^[0-9]+$/.test(id)) return <NotFoundPage />;
  return <Reading entity={entity} id={id} />;
}

function Reading({ entity, id }: { entity: "b" | "c"; id: string }) {
  const { t } = useLingui();
  const base = useKnownBase("grocy");
  const title = entity === "b" ? t`Grocy battery ${id}` : t`Grocy chore ${id}`;
  const path = entity === "b" ? "battery" : "chore";

  return (
    <div className="flex max-w-xl flex-col gap-5">
      <header className="flex flex-col gap-2">
        <h1 className="break-words text-title font-bold">{title}</h1>
        <p className="text-ink-2">
          {entity === "b" ? t`The code on this label names a battery in Grocy.` : t`The code on this label names a chore in Grocy.`}
        </p>
      </header>
      <div className="flex flex-wrap items-center gap-3">
        {base ? (
          <a href={`${base}/${path}/${id}`} target="_blank" rel="noopener noreferrer" className={PRIMARY_BUTTON}>
            {t`Open in Grocy`}&nbsp;<span aria-hidden="true">↗</span>
          </a>
        ) : (
          <p className="text-ink-2">{t`The hub does not know the Grocy address yet. Open a product from Grocy once, or open it in Grocy yourself.`}</p>
        )}
        <Link to="/scan" className={SECONDARY_BUTTON}>
          {t`Scan again`}
        </Link>
      </div>
    </div>
  );
}
