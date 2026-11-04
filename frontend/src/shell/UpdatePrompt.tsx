import { useLingui } from "@lingui/react/macro";
import { applyUpdate, useNeedRefresh } from "../app/updates";
import { StatusBadge } from "./StatusBadge";

/** Non-blocking note when a new version of the app is waiting; the person picks the moment. */
export function UpdatePrompt() {
  const { t } = useLingui();
  if (!useNeedRefresh()) return null;
  return (
    <div className="mb-4 flex flex-wrap items-center gap-4">
      <div role="status">
        <StatusBadge state="warn" label={t`New version available`} />
      </div>
      <button
        type="button"
        onClick={applyUpdate}
        className="press inline-flex h-11 items-center rounded-r2 border border-line-strong bg-surface px-4 text-small font-bold text-ink focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-link"
      >
        {t`Reload`}
      </button>
    </div>
  );
}
