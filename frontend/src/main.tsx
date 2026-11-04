import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { createQueryClient } from "./app/queryClient";
import { createAppRouter } from "./app/router";
import { installUnauthorizedGuard } from "./app/session";
import { initI18n, pickLanguage } from "./i18n";
import "./index.css";
import { applyTheme, readTheme } from "./shell/theme";

async function serverDefaultLanguage(): Promise<string | undefined> {
  try {
    const response = await fetch("/api/info", { credentials: "same-origin" });
    if (!response.ok) return undefined;
    return ((await response.json()) as { default_language?: string }).default_language;
  } catch {
    return undefined;
  }
}

async function start() {
  await initI18n(pickLanguage(await serverDefaultLanguage()));
  applyTheme(readTheme());
  const queryClient = createQueryClient();
  installUnauthorizedGuard(queryClient);
  const router = createAppRouter();
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <App queryClient={queryClient} router={router} />
    </StrictMode>,
  );
}

// The service worker only exists in the production build (the dev server has none).
if (import.meta.env.PROD && "serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    void navigator.serviceWorker.register("/sw.js").catch(() => {
      /* no service worker (private window, blocked): the app works the same, just not offline-first */
    });
  });
}

void start();
