import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { initI18n, pickLanguage } from "./i18n";
import "./index.css";

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
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}

void start();
