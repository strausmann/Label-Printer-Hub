import { useLingui } from "@lingui/react/macro";
import { Link } from "@tanstack/react-router";
import type { ReactNode } from "react";
import { useFeature } from "../app/session";
import { JobsIcon, OverviewIcon, PrintersIcon, ScanIcon, SheetsIcon } from "./icons";
import { useNavLabels } from "./labels";

const TAB =
  "press relative flex h-16 flex-col items-center justify-center gap-0.5 text-small text-ink-2 data-[status=active]:font-bold data-[status=active]:text-ink";

function Tab({ to, icon, label }: { to: "/" | "/printers" | "/jobs" | "/sheets"; icon: ReactNode; label: string }) {
  return (
    <Link to={to} activeOptions={{ exact: to === "/" || to === "/sheets" }} className={TAB}>
      {/* A bar over the active tab says "here" without relying on colour. */}
      <span className="absolute top-0 h-0.5 w-8 rounded-full bg-transparent in-data-[status=active]:bg-link" aria-hidden="true" />
      {icon}
      <span>{label}</span>
    </Link>
  );
}

/**
 * Phone navigation (< 1024 px): Overview · Printers · Scan (large, centre) · Jobs · Sheets.
 * Five fixed slots so Scan stays in the middle while Sheets is hidden (spec 5.3).
 */
export function TabBar() {
  const { t } = useLingui();
  const labels = useNavLabels();
  const sheets = useFeature("sheets");

  return (
    // `data-tabbar` is a contract: SheetTypeCombobox queries it to keep its list above this bar. Keep the attribute if the bar is rebuilt.
    <nav
      aria-label={t`Tabs`}
      data-tabbar=""
      className="fixed inset-x-0 bottom-0 z-20 grid grid-cols-5 border-t border-line bg-surface pb-[env(safe-area-inset-bottom)] lg:hidden"
    >
      <Tab to="/" icon={<OverviewIcon />} label={labels.entry.overview!} />
      <Tab to="/printers" icon={<PrintersIcon />} label={labels.entry.printers!} />
      <Link
        to="/scan"
        className="press relative -mt-5 flex min-w-16 flex-col items-center justify-start gap-1 text-small font-bold text-ink"
      >
        <span className="flex size-14 items-center justify-center rounded-full bg-accent text-accent-ink">
          <ScanIcon width={28} height={28} />
        </span>
        <span>{labels.entry.scan}</span>
      </Link>
      <Tab to="/jobs" icon={<JobsIcon />} label={labels.entry.jobs!} />
      {sheets ? <Tab to="/sheets" icon={<SheetsIcon />} label={labels.entry.sheets!} /> : <div aria-hidden="true" />}
    </nav>
  );
}
