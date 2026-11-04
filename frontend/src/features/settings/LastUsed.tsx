import { useLingui } from "@lingui/react/macro";

/** When a key was last used, or that it never was. */
export function LastUsed({ at }: { at: string | null }) {
  const { t, i18n } = useLingui();
  if (!at) return <>{t`Never used`}</>;
  const when = i18n.date(new Date(at), { dateStyle: "medium", timeStyle: "short" });
  return <>{t`Last used ${when}`}</>;
}
