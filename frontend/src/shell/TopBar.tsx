import { useLingui } from "@lingui/react/macro";
import { Link } from "@tanstack/react-router";
import { Button } from "react-aria-components";
import { useSession } from "../app/session";
import { GlobalSearch } from "../features/search";
import { ScanIcon, SignOutIcon } from "./icons";
import { ThemeSwitch } from "./ThemeSwitch";

const ICON_BUTTON =
  "press flex size-11 items-center justify-center rounded-r2 text-ink-2 transition-colors duration-150 hover:bg-sunken hover:text-ink data-[focus-visible]:outline-3 data-[focus-visible]:outline-offset-1 data-[focus-visible]:outline-link";

/** Global search and the Scan button (spec 5.3). On a phone Scan lives in the tab bar. */
export function TopBar() {
  const { t } = useLingui();
  const session = useSession();

  return (
    <header className="sticky top-0 z-10 flex h-16 items-center gap-2 border-b border-line bg-surface px-4 lg:gap-3 lg:px-8">
      <GlobalSearch />

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
