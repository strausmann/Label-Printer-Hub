// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useLingui } from "@lingui/react/macro";
import { getRouteApi, Link } from "@tanstack/react-router";
import type { ReactNode } from "react";
import { Button } from "react-aria-components";
import { ApiError } from "../../api/client";
import { useKnownBase } from "../integrations/useKnownBase";
import { safeHref } from "../lookup/apps";
import { NotFoundPage } from "../../pages/placeholders";
import { PANEL, PRIMARY_BUTTON, SECONDARY_BUTTON } from "../ui";
import { useGrocyObject, type GrocyBattery, type GrocyChore } from "./grocyObject";

const route = getRouteApi("/grocycode/$entity/$id");

/**
 * Where a scanned battery or chore code lands: a few facts about it from Grocy, and a link to it
 * in Grocy. The link comes with the answer; until there is one, the address the hub saw earlier does.
 */
export function GrocycodePage() {
  const { entity, id } = route.useParams();
  if ((entity !== "b" && entity !== "c") || !/^[0-9]+$/.test(id)) return <NotFoundPage />;
  return <Reading entity={entity} id={id} />;
}

function Reading({ entity, id }: { entity: "b" | "c"; id: string }) {
  const { t, i18n } = useLingui();
  const query = useGrocyObject(entity, id);
  const known = useKnownBase("grocy");
  const kind = entity === "b" ? t`Grocy battery ${id}` : t`Grocy chore ${id}`;
  const path = entity === "b" ? "battery" : "chore";
  const data = query.data;
  const notFound = query.error instanceof ApiError && query.error.status === 404;
  const href = safeHref(data?.url) ?? (known && !notFound ? `${known}/${path}/${id}` : null);

  const when = (value: string | null | undefined) =>
    value ? new Date(value).toLocaleString(i18n.locale, { dateStyle: "medium", timeStyle: "short" }) : t`Never`;

  return (
    <div className="flex max-w-xl flex-col gap-5">
      <header className="flex flex-col gap-1">
        <p className="text-small text-ink-3">{kind}</p>
        <h1 className="break-words text-title font-bold">{data?.name ?? (notFound ? t`Not found in Grocy` : kind)}</h1>
        {data?.description && <p className="break-words text-ink-2">{data.description}</p>}
      </header>

      {query.isPending && <p role="status" className="text-ink-2">{t`Loading…`}</p>}

      {notFound && (
        <p className="text-ink-2">{entity === "b" ? t`Grocy has no battery with the ID ${id}.` : t`Grocy has no chore with the ID ${id}.`}</p>
      )}

      {query.isError && !notFound && <ErrorNote error={query.error} onRetry={() => void query.refetch()} />}

      {data && entity === "b" && (
        <Facts>
          <Fact label={t`Last charged`}>{when((data as GrocyBattery).last_charged)}</Fact>
          <Fact label={t`Next charge`}>{when((data as GrocyBattery).next_estimated_charge)}</Fact>
          <Fact label={t`Charge cycles`}>{(data as GrocyBattery).charge_cycles}</Fact>
        </Facts>
      )}
      {data && entity === "c" && (
        <Facts>
          <Fact label={t`Last done`}>{when((data as GrocyChore).last_tracked)}</Fact>
          <Fact label={t`Next due`}>{when((data as GrocyChore).next_estimated_execution)}</Fact>
          {(data as GrocyChore).assigned_to && <Fact label={t`Assigned to`}>{(data as GrocyChore).assigned_to}</Fact>}
        </Facts>
      )}

      <div className="flex flex-wrap items-center gap-3">
        {href && (
          <a href={href} target="_blank" rel="noopener noreferrer" className={PRIMARY_BUTTON}>
            {t`Open in Grocy`}&nbsp;<span aria-hidden="true">↗</span>
          </a>
        )}
        <Link to="/scan" className={SECONDARY_BUTTON}>
          {t`Scan again`}
        </Link>
      </div>
    </div>
  );
}

function ErrorNote({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const { t } = useLingui();
  if (error instanceof ApiError && error.status === 503 && error.code === "integration_not_configured") {
    return (
      <div className="flex flex-col gap-2">
        <p className="text-ink-2">{t`Grocy is not set up yet, so this cannot be shown.`}</p>
        <Link to="/settings/integrations" className="w-fit text-link underline underline-offset-2">
          {t`Open Settings › Integrations`}
        </Link>
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-2">
      <p role="alert">{t`The details could not be loaded.`}</p>
      <Button className="w-fit text-link underline underline-offset-2" onPress={onRetry}>
        {t`Try again`}
      </Button>
    </div>
  );
}

function Facts({ children }: { children: ReactNode }) {
  // Label above value on a phone, side by side from the small breakpoint: no table, nothing to scroll sideways.
  return <dl className={`${PANEL} grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-[max-content_minmax(0,1fr)]`}>{children}</dl>;
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5 sm:contents">
      <dt className="text-small text-ink-3">{label}</dt>
      <dd className="min-w-0 break-words font-bold tabular-nums">{children}</dd>
    </div>
  );
}
