import { useLingui } from "@lingui/react/macro";
import { Link } from "@tanstack/react-router";
import { Button, Input, SearchField } from "react-aria-components";
import { useSession } from "../app/session";
import { ScanIcon, SearchIcon, SignOutIcon } from "./icons";
import { ThemeSwitch } from "./ThemeSwitch";

const ICON_BUTTON =
  "press flex size-11 items-center justify-center rounded-r2 text-ink-2 transition-colors duration-150 hover:bg-sunken hover:text-ink data-[focus-visible]:outline-3 data-[focus-visible]:outline-offset-1 data-[focus-visible]:outline-link";

/** Global search and the Scan button (spec 5.3). On a phone Scan lives in the tab bar. */
export function TopBar() {
  const { t } = useLingui();
  const session = useSession();

  return (
    <header className="sticky top-0 z-10 flex h-16 items-center gap-2 border-b border-line bg-surface px-4 lg:gap-3 lg:px-8">
      {/* Global search (printers, jobs, sheet IDs, ASNs, label codes) is wired by the modules that own those. */}
      <SearchField aria-label={t`Search`} className="group relative min-w-0 flex-1 lg:max-w-md lg:flex-none lg:basis-96">
        <SearchIcon width={18} height={18} className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-ink-3" />
        <Input
          placeholder={t`Search`}
          className="h-11 w-full rounded-r2 border border-line-strong bg-sunken pr-3 pl-10 text-ink placeholder:text-ink-3 data-[focus-visible]:outline-3 data-[focus-visible]:outline-offset-2 data-[focus-visible]:outline-link"
        />
      </SearchField>

      <Link
        to="/scan"
        className="press hidden h-11 items-center gap-2 rounded-r2 bg-accent px-4 font-bold text-accent-ink transition-colors duration-150 hover:bg-amber-600 hover:text-white lg:inline-flex"
      >
        <ScanIcon width={20} height={20} />
        <span>{t`Scan`}</span>
      </Link>

      <div className="ml-auto flex items-center gap-1">
        <ThemeSwitch />
        <Button aria-label={t`Sign out`} onPress={() => void session.signOut()} className={ICON_BUTTON}>
          <SignOutIcon />
        </Button>
      </div>
    </header>
  );
}
