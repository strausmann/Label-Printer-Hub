import { useLingui } from "@lingui/react/macro";
import {
  createRootRoute,
  createRoute,
  createRouter,
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
  CalibrationPage,
  KeptPage,
  NotFoundPage,
  ScanPage,
  SheetArchivePage,
  SheetsPage,
} from "../pages/placeholders";
import { IntegrationPage } from "../features/integrations/IntegrationPage";
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
          await apiFetch<components["schemas"]["ApiKeyCreateResponse"]>("/api/admin/api-keys", {
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
  page("/cart", CartPage),
  page("/scan", ScanPage),
  settingsRoute.addChildren([
    settingsChild("/", General),
    settingsChild("/printers", SettingsPrinters),
    settingsChild("/integrations", Integrations),
    settingsChild("/access", AccessKeys),
    settingsChild("/jobs", Jobs),
    settingsChild("/system", System),
  ]),
  page("/sheets", SheetsPage),
  page("/sheets/archive", SheetArchivePage),
  page("/calibration", CalibrationPage),
  page("/asn", AsnPage),
  page("/kept", KeptPage),
  signInRoute,
]);

export function createAppRouter(options: { history?: RouterHistory } = {}) {
  return createRouter({ routeTree, history: options.history, defaultPreload: "intent" });
}

declare module "@tanstack/react-router" {
  interface Register {
    router: ReturnType<typeof createAppRouter>;
  }
}
