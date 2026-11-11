import { registerSW } from "virtual:pwa-register";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { createQueryClient } from "./app/queryClient";
import { createAppRouter } from "./app/router";
import { installUnauthorizedGuard } from "./app/session";
import { startUpdates } from "./app/updates";
import { initI18n, pickLanguage } from "./i18n";
import "./index.css";
import { applyTheme, readTheme } from "./shell/theme";
import { trackVisibleViewport } from "./shell/viewport";

async function serverDefaultLanguage(): Promise<string | undefined> {
  try {
    const response = await fetch("/api/v1/info", { credentials: "same-origin" });
    if (!response.ok) return undefined;
    return ((await response.json()) as { default_language?: string }).default_language;
  } catch {
    return undefined;
  }
}

async function start() {
  await initI18n(pickLanguage(await serverDefaultLanguage()));
  applyTheme(readTheme());
  trackVisibleViewport();
  const queryClient = createQueryClient();
  installUnauthorizedGuard(queryClient);
  const router = createAppRouter();
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <App queryClient={queryClient} router={router} />
    </StrictMode>,
  );
}

// The service worker only exists in the production build (the dev server has none). A new
// version waits and the shell offers "Reload" (src/app/updates.ts).
if (import.meta.env.PROD) startUpdates(registerSW);

void start();
