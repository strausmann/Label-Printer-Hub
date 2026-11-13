import { useLingui } from "@lingui/react/macro";
import { applyUpdate, useNeedRefresh, useUpdating } from "../app/updates";
import { StatusBadge } from "./StatusBadge";

/** Non-blocking note when a new version of the app is waiting; the person picks the moment. */
export function UpdatePrompt() {
  const { t } = useLingui();
  const needRefresh = useNeedRefresh();
  const updating = useUpdating();
  if (!needRefresh) return null;
  return (
    <div className="mb-4 flex flex-wrap items-center gap-4">
      <div role="status">
        <StatusBadge state="warn" label={t`New version available`} />
        {/* A changed button label is not read out; this region says it once. */}
        <span className="sr-only">{updating ? t`Updating…` : ""}</span>
      </div>
      {/* aria-disabled, not disabled: a disabled button drops the focus to the page. A second press is ignored by applyUpdate. */}
      <button
        type="button"
        onClick={() => void applyUpdate()}
        aria-disabled={updating || undefined}
        className="press inline-flex h-11 items-center rounded-r2 border border-line-strong bg-surface px-4 text-small font-bold text-ink focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-link aria-disabled:opacity-60"
      >
        {updating ? t`Updating…` : t`Reload`}
      </button>
    </div>
  );
}
