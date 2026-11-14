// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useLingui } from "@lingui/react/macro";
import {
  createRootRoute,
  createRoute,
  createRouter,
  defaultParseSearch,
  defaultStringifySearch,
  getRouteApi,
  Outlet,
  useLocation,
  useRouter,
  type RouterHistory,
} from "@tanstack/react-router";
import { useEffect } from "react";
import { Button } from "react-aria-components";
import { apiFetch } from "../api/client";
import type { components } from "../api/schema.gen";
import {
  AsnPage,
  KeptPage,
  NotFoundPage,
} from "../pages/placeholders";
import { CalibrationPage } from "../features/calibration/CalibrationPage";
import { IntegrationPage } from "../features/integrations/IntegrationPage";
import { AboutPage } from "../features/about/AboutPage";
import { JobPage } from "../features/jobs/JobDetail";
import { JobsPage } from "../features/jobs/JobsPage";
import { CartPage } from "../features/lookup/CartPage";
import { AssetPage, LocPage, LookupPage, ProductPage, SpoolPage } from "../features/lookup/ItemView";
import { AccessKeys } from "../features/settings/AccessKeys";
import { Integrations } from "../features/settings/Integrations";
import { Printers as SettingsPrinters } from "../features/settings/Printers";
import { General, Jobs } from "../features/settings/sections";
import { SettingsLayout } from "../features/settings/SettingsPage";
import { System } from "../features/settings/System";
import { ScanScreen } from "../features/scan/ScanScreen";
import { SheetArchivePage } from "../features/archive/ArchivePage";
import { parseArchiveSearch } from "../features/archive/search";
import { parseSheetCode } from "../features/sheets/resolver";
import { parseSheetsSearch } from "../features/sheets/search";
import { SheetsPage } from "../features/sheets/SheetsPage";
import { SheetDetail } from "../features/sheets/SheetDetail";
import { OverviewPage } from "../features/overview/OverviewPage";
import { PrinterPage } from "../features/printers/PrinterDetail";
import { PrintersPage } from "../features/printers/PrintersPage";
import { AppShell } from "../shell/AppShell";
import { BootstrapKeyCreated } from "../shell/BootstrapKeyCreated";
import { PRIMARY_BUTTON, SignIn } from "../shell/SignIn";
import { useSession } from "./session";

/** A sign-in return target must stay on this site: a path, never `//host` or a scheme. */
export function safeRedirect(value: unknown): string | undefined {
  if (typeof value !== "string") return undefined;
  if (!value.startsWith("/") || value.startsWith("//") || value.startsWith("/\\")) return undefined;
  // Browsers drop tabs and newlines inside a URL, so "/\t/host" would become "//host".
  // eslint-disable-next-line no-control-regex
  if (/[\u0000-\u001f\u007f]/.test(value)) return undefined;
  if (value === "/sign-in" || value.startsWith("/sign-in?")) return undefined;
  return value;
}

/** Replaces the current history entry (a redirect should not leave a back-button trap). */
function RedirectTo({ href }: { href: string }) {
  const router = useRouter();
  useEffect(() => {
    router.history.replace(href);
  }, [router, href]);
  return null;
}

function Splash() {
  const { t } = useLingui();
  return (
    <div role="status" className="grid min-h-dvh place-items-center text-ink-2">
      {t`Loading…`}
    </div>
  );
}

function Unreachable({ onRetry }: { onRetry: () => void }) {
  const { t } = useLingui();
  return (
    <main className="grid min-h-dvh place-items-center p-4">
      <div className="flex max-w-sm flex-col items-start gap-4">
        <h1 className="text-title font-bold">{t`The server cannot be reached.`}</h1>
        <Button onPress={onRetry} className={PRIMARY_BUTTON}>
          {t`Try again`}
        </Button>
      </div>
    </main>
  );
}

function BootstrapScreen() {
  const session = useSession();
  return (
    <BootstrapKeyCreated
      onCreate={async () =>
        (
          await apiFetch<components["schemas"]["ApiKeyCreateResponse"]>("/api/v1/admin/api-keys", {
            method: "POST",
            json: { name: "First admin key", scopes: ["admin"] },
          })
        ).plaintext
      }
      onContinue={session.signIn}
    />
  );
}

/**
 * Decides what the visitor sees: sign-in while signed out (remembering where they were),
 * the bootstrap screen on a bootstrap session (D7), the shell otherwise.
 */
function RootLayout() {
  const session = useSession();
  const location = useLocation();
  const onSignInPage = location.pathname === "/sign-in";

  if (session.isPending) return <Splash />;
  if (session.isError) return <Unreachable onRetry={() => void session.refetch()} />;
  if (!session.signedIn) {
    if (onSignInPage) return <Outlet />;
    return <RedirectTo href={`/sign-in?redirect=${encodeURIComponent(location.href)}`} />;
  }
  if (session.bootstrap) return <BootstrapScreen />;
  if (onSignInPage) return <Outlet />;
  return (
    <AppShell>
      <Outlet />
    </AppShell>
  );
}

const rootRoute = createRootRoute({ component: RootLayout, notFoundComponent: NotFoundPage });

const signInApi = getRouteApi("/sign-in");

function SignInRoute() {
  const session = useSession();
  const { redirect } = signInApi.useSearch();
  if (session.signedIn) return session.bootstrap ? null : <RedirectTo href={safeRedirect(redirect) ?? "/"} />;
  return <SignIn onSignIn={session.signIn} />;
}

const page = <P extends string>(path: P, component: () => React.JSX.Element) =>
  createRoute({ getParentRoute: () => rootRoute, path, component });

const text = (value: unknown): string | undefined => (typeof value === "string" && value !== "" ? value : undefined);
const sheetTypeKey = (value: unknown): string | undefined => {
  const key = text(value);
  return key !== undefined && key.length <= 64 ? key : undefined;
};

// The search parameters other pages link with (`<Link to="/cart" search={{ sheet }}>`), declared
// here so the typed links compile; the pages read them. A value that is not a sheet code is dropped.
// Every key stays in the result even when rejected: the router merges the result over the raw
// query string, so leaving it out would let the unchecked value through.
const cartRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/cart",
  component: CartPage,
  validateSearch: (search: Record<string, unknown>): { sheet?: string | undefined } => {
    const sheet = text(search.sheet);
    return { sheet: sheet && parseSheetCode(`sheet:${sheet}`) ? sheet : undefined };
  },
});

const archiveRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/sheets/archive",
  component: SheetArchivePage,
  validateSearch: parseArchiveSearch,
});

const sheetsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/sheets",
  component: SheetsPage,
  validateSearch: parseSheetsSearch,
});

const calibrationRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/calibration",
  component: CalibrationPage,
  validateSearch: (search: Record<string, unknown>): { printer?: string | undefined; tray?: string | undefined; type?: string | undefined } => ({
    printer: text(search.printer),
    tray: text(search.tray),
    // A sheet type key is at most 64 characters (the print request's limit); anything longer is not one.
    type: sheetTypeKey(search.type),
  }),
});

// Settings is a layout (admin gate and section navigation) with one child per section.
const settingsRoute = createRoute({ getParentRoute: () => rootRoute, path: "/settings", component: SettingsLayout });
const settingsChild = <P extends string>(path: P, component: () => React.JSX.Element) =>
  createRoute({ getParentRoute: () => settingsRoute, path, component });

const signInRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/sign-in",
  component: SignInRoute,
  // The key stays in the result even when rejected: the router merges the result over the
  // raw query string, so leaving it out would let the unchecked value through.
  validateSearch: (search: Record<string, unknown>): { redirect: string | undefined } => ({
    redirect: safeRedirect(search.redirect),
  }),
});

const routeTree = rootRoute.addChildren([
  page("/", OverviewPage),
  page("/printers", PrintersPage),
  page("/printers/$printerId", PrinterPage),
  page("/jobs", JobsPage),
  page("/jobs/$jobId", JobPage),
  page("/integrations/$app", IntegrationPage),
  page("/lookup/$app/$id", LookupPage),
  // The paths printed in QR codes: they open the item view too.
  page("/loc/$id", LocPage),
  page("/asset/$id", AssetPage),
  page("/spool/$id", SpoolPage),
  page("/product/$id", ProductPage),
  cartRoute,
  page("/about", AboutPage),
  page("/scan", ScanScreen),
  settingsRoute.addChildren([
    settingsChild("/", General),
    settingsChild("/printers", SettingsPrinters),
    settingsChild("/integrations", Integrations),
    settingsChild("/access", AccessKeys),
    settingsChild("/jobs", Jobs),
    settingsChild("/system", System),
  ]),
  sheetsRoute,
  archiveRoute,
  // The second path is the one printed in the QR code of a sheet.
  page("/sheets/$code", SheetDetail),
  page("/sheet/$code", SheetDetail),
  calibrationRoute,
  page("/asn", AsnPage),
  page("/kept", KeptPage),
  signInRoute,
]);

/**
 * A sheet type key is text, whatever it looks like. The router's own parser decodes every value as JSON, so `?type=4736`
 * would arrive as the number 4736 and `?type=1e3` as 1000: the key is read from the raw query instead and written without
 * quotes, so a key such as "007" or "4736" survives the address.
 */
const RAW_KEYS = ["type"] as const;

export function parseAppSearch(searchStr: string): Record<string, unknown> {
  const parsed: Record<string, unknown> = defaultParseSearch(searchStr);
  const raw = new URLSearchParams(searchStr);
  for (const key of RAW_KEYS) {
    const value = raw.get(key);
    if (value !== null) parsed[key] = value;
  }
  return parsed;
}

export function stringifyAppSearch(search: Record<string, unknown>): string {
  const rest: Record<string, unknown> = { ...search };
  const raw = new URLSearchParams();
  for (const key of RAW_KEYS) {
    const value = rest[key];
    delete rest[key];
    if (typeof value === "string") raw.set(key, value);
    else if (typeof value === "number" && Number.isFinite(value)) raw.set(key, String(value));
  }
  const base = defaultStringifySearch(rest).replace(/^\?/, "");
  const extra = raw.toString();
  const all = [base, extra].filter((part) => part !== "").join("&");
  return all === "" ? "" : `?${all}`;
}

export function createAppRouter(options: { history?: RouterHistory } = {}) {
  return createRouter({
    routeTree,
    history: options.history,
    defaultPreload: "intent",
    parseSearch: parseAppSearch,
    stringifySearch: stringifyAppSearch,
  });
}

declare module "@tanstack/react-router" {
  interface Register {
    router: ReturnType<typeof createAppRouter>;
  }
}
