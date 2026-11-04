import { useLingui } from "@lingui/react/macro";
import { useInfo } from "../../app/session";
import { StatusBadge, type BadgeState } from "../../shell/StatusBadge";
import { PANEL, SECONDARY_BUTTON } from "../ui";
import { useHealth, useLogs, useReadiness } from "./api";
import { Section } from "./sections";


function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-6 gap-y-1 border-b border-line py-2 last:border-b-0">
      <dt className="w-40 shrink-0 text-ink-2">{label}</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </div>
  );
}

function LevelBadge({ level }: { level: string }) {
  const state: BadgeState = /error|critical/i.test(level) ? "bad" : "warn";
  return <StatusBadge state={state} label={level} />;
}

export function System() {
  const { t, i18n } = useLingui();
  const info = useInfo().data;
  const health = useHealth();
  const readiness = useReadiness();
  const logs = useLogs();
  const entries = [...(logs.data ?? [])].reverse();

  const readyState: BadgeState = readiness.data?.status === "ready" ? "ok" : readiness.data?.status === "degraded" ? "warn" : "bad";
  const readyLabel = { ready: t`Ready`, degraded: t`Degraded`, "not-ready": t`Not ready` }[readiness.data?.status ?? "not-ready"];
  const failing = Object.entries(readiness.data?.checks ?? {}).filter(([, c]) => c.status !== "ok" && c.status !== "skipped");

  return (
    <div className="flex flex-col gap-10">
      <Section title={t`System`}>
        <dl className={`${PANEL} max-w-xl`}>
          <Row label={t`Version`}>
            <span className="font-mono">{info?.version ?? "…"}</span>
          </Row>
          <Row label={t`Revision`}>
            <span className="font-mono">{info?.revision ?? "…"}</span>
          </Row>
          <Row label={t`Health`}>
            {health.isPending ? t`Checking…` : <StatusBadge state={health.isSuccess ? "ok" : "bad"} label={health.isSuccess ? t`Healthy` : t`Not reachable`} />}
          </Row>
          <Row label={t`Readiness`}>
            {readiness.isPending ? (
              t`Checking…`
            ) : readiness.isError ? (
              <StatusBadge state="bad" label={t`Not reachable`} />
            ) : (
              <div className="flex flex-col gap-1">
                <StatusBadge state={readyState} label={readyLabel} />
                {failing.map(([name, check]) => (
                  <span key={name} className="text-small text-ink-2">
                    {name}: {check.status}
                    {check.detail ? ` — ${check.detail}` : ""}
                  </span>
                ))}
              </div>
            )}
          </Row>
        </dl>
        <div className="flex flex-wrap gap-3">
          <a href="/api/v1/settings/export" download className={`${SECONDARY_BUTTON} no-underline`}>
            {t`Download settings`}
          </a>
          <a href="/docs" className={`${SECONDARY_BUTTON} no-underline`}>
            {t`API documentation`}
          </a>
        </div>
        <p className="max-w-prose text-small text-ink-2">
          {t`The download holds the settings that are not secret and not set by the container, as JSON. Keys and tokens are never included.`}
        </p>
      </Section>

      <Section title={t`Recent warnings and errors`} intro={t`The last 200 records of level warning or higher, newest first. They are kept in memory and start over with the container.`}>
        {logs.isPending ? (
          <p role="status" className="text-ink-2">{t`Loading…`}</p>
        ) : logs.isError ? (
          <p role="alert">{t`The log could not be loaded.`}</p>
        ) : entries.length === 0 ? (
          <p className="text-ink-2">{t`No warnings or errors recorded.`}</p>
        ) : (
          <div className="overflow-x-auto rounded-r3 border border-line bg-surface">
            <table aria-label={t`Recent warnings and errors`} className="w-full min-w-[48rem] border-collapse text-left text-small">
              <thead>
                <tr className="bg-sunken">
                  <th scope="col" className="px-3 py-2 font-bold">{t`Time`}</th>
                  <th scope="col" className="px-3 py-2 font-bold">{t`Level`}</th>
                  <th scope="col" className="px-3 py-2 font-bold">{t`Source`}</th>
                  <th scope="col" className="px-3 py-2 font-bold">{t`Message`}</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((entry, index) => (
                  <tr key={`${entry.ts}-${index}`} className="border-t border-line align-top">
                    <td className="whitespace-nowrap px-3 py-2 font-mono">{i18n.date(new Date(entry.ts), { dateStyle: "short", timeStyle: "medium" })}</td>
                    <td className="px-3 py-2"><LevelBadge level={entry.level} /></td>
                    <td className="max-w-48 break-all px-3 py-2 font-mono">{entry.logger}</td>
                    <td className="min-w-72 break-words px-3 py-2">{entry.message}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>
    </div>
  );
}

