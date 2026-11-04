import { useLingui } from "@lingui/react/macro";
import type { ReactNode } from "react";
import { Sidebar } from "./Sidebar";
import { TabBar } from "./TabBar";
import { TopBar } from "./TopBar";

/** Sidebar on desktop, bottom tab bar on a phone (breakpoint 1024 px), search and Scan on top. */
export function AppShell({ children }: { children: ReactNode }) {
  const { t } = useLingui();
  return (
    <div className="flex min-h-dvh">
      <a
        href="#content"
        onClick={(event) => {
          event.preventDefault();
          document.getElementById("content")?.focus();
        }}
        className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:rounded-r2 focus:bg-surface focus:px-4 focus:py-2 focus:font-bold"
      >
        {t`Skip to content`}
      </a>
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar />
        <main id="content" tabIndex={-1} className="flex-1 p-4 pb-32 outline-none lg:p-8 lg:pb-8">
          {children}
        </main>
      </div>
      <TabBar />
    </div>
  );
}
