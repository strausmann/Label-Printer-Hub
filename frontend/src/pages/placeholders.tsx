import { useLingui } from "@lingui/react/macro";
import { Link } from "@tanstack/react-router";

/**
 * Stand-ins for pages that later tasks build. Each one is replaced by importing the real
 * page in `app/router.tsx`; until then the shell has something honest to show.
 */
function PagePlaceholder({ title }: { title: string }) {
  const { t } = useLingui();
  return (
    <div>
      <h1 className="text-title font-bold">{title}</h1>
      <p className="mt-2 text-ink-2">{t`This page is not available yet.`}</p>
    </div>
  );
}

export function JobsPage() {
  const { t } = useLingui();
  return <PagePlaceholder title={t`Jobs`} />;
}
export function JobPage() {
  const { t } = useLingui();
  return <PagePlaceholder title={t`Job`} />;
}
export function LookupPage() {
  const { t } = useLingui();
  return <PagePlaceholder title={t`Item`} />;
}
export function ScanPage() {
  const { t } = useLingui();
  return <PagePlaceholder title={t`Scan`} />;
}
export function SettingsPage() {
  const { t } = useLingui();
  return <PagePlaceholder title={t`Settings`} />;
}

/* Modules that have not shipped: their navigation entries stay hidden until `features` says so. */
export function SheetsPage() {
  const { t } = useLingui();
  return <PagePlaceholder title={t`Sheets`} />;
}
export function SheetArchivePage() {
  const { t } = useLingui();
  return <PagePlaceholder title={t`Sheet archive`} />;
}
export function CalibrationPage() {
  const { t } = useLingui();
  return <PagePlaceholder title={t`Calibration`} />;
}
export function AsnPage() {
  const { t } = useLingui();
  return <PagePlaceholder title={t`Paperless ASN`} />;
}
export function KeptPage() {
  const { t } = useLingui();
  return <PagePlaceholder title={t`Kept / Hangar / Grocy`} />;
}

export function NotFoundPage() {
  const { t } = useLingui();
  return (
    <div>
      <h1 className="text-title font-bold">{t`Page not found`}</h1>
      <p className="mt-2">
        <Link to="/" className="text-link underline underline-offset-2">
          {t`Back to the overview`}
        </Link>
      </p>
    </div>
  );
}
