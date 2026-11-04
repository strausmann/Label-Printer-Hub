import { I18nProvider, useLingui } from "@lingui/react";
import { i18n } from "./i18n";
import { messages } from "./i18n/messages";

function Placeholder() {
  const { _ } = useLingui();
  return (
    <main className="mx-auto max-w-3xl p-6">
      <h1 className="text-title font-bold">{_(messages.appName)}</h1>
      <p className="mt-2 text-ink-2">{_(messages.loading)}</p>
    </main>
  );
}

/** Replaced by the shell in Task 9. */
export function App() {
  return (
    <I18nProvider i18n={i18n}>
      <Placeholder />
    </I18nProvider>
  );
}
