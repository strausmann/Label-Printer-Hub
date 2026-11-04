import { useLingui } from "@lingui/react/macro";
import type { ReactNode } from "react";
import { SECTION_HEADING } from "../ui";
import { useSettings } from "./api";
import { SectionForm } from "./SectionForm";

/** A titled block of a settings page. */
export function Section({ title, intro, children, label }: { title: string; intro?: ReactNode; children: ReactNode; label?: string }) {
  return (
    <section aria-label={label ?? title} className="flex flex-col gap-4">
      <div>
        <h2 className={SECTION_HEADING}>{title}</h2>
        {intro ? <p className="mt-1 max-w-prose text-ink-2">{intro}</p> : null}
      </div>
      {children}
    </section>
  );
}

/** Waits for the settings list, then hands it on. */
export function WithSettings({ children }: { children: (views: NonNullable<ReturnType<typeof useSettings>["data"]>) => ReactNode }) {
  const { t } = useLingui();
  const settings = useSettings();
  if (settings.isPending) return <p role="status" className="text-ink-2">{t`Loading…`}</p>;
  if (settings.isError || !settings.data) return <p role="alert">{t`The settings could not be loaded.`}</p>;
  return <>{children(settings.data)}</>;
}

export function General() {
  const { t } = useLingui();
  return (
    <Section title={t`General`} intro={t`The name in the title bar, the language new visitors see, and the address of this hub.`}>
      <WithSettings>
        {(views) => (
          <SectionForm
            views={views}
            fields={[
              { key: "general.display_name", label: t`Display name` },
              { key: "general.language", label: t`Language`, choiceLabels: { en: "English", de: "Deutsch" } },
              { key: "general.time_zone", label: t`Time zone`, description: t`An IANA name such as Europe/Berlin.` },
              { key: "general.public_url", label: t`Public URL`, description: undefined },
            ]}
          />
        )}
      </WithSettings>
    </Section>
  );
}

export function Jobs() {
  const { t } = useLingui();
  return (
    <Section title={t`Jobs`} intro={t`How long finished jobs stay in the history.`}>
      <WithSettings>
        {(views) => <SectionForm views={views} fields={[{ key: "jobs.retention_days", label: t`Keep finished jobs for (days)` }]} />}
      </WithSettings>
    </Section>
  );
}
