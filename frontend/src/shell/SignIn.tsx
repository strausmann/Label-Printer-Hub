// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { PRIMARY_BUTTON } from "../features/ui";
import { useLingui } from "@lingui/react/macro";
import { useState, type FormEvent } from "react";
import { Button, Input, Label, TextField } from "react-aria-components";
import { ApiError } from "../api/client";
import { SourceLink } from "../features/about/SourceLink";
import { messages } from "../i18n/messages";

// Defined with the other button styles in `features/ui`; re-exported because the screens import it from here.
export { PRIMARY_BUTTON };

export const FIELD =
  "h-11 w-full rounded-r2 border border-line-strong bg-sunken px-3 text-ink placeholder:text-ink-3 data-[focus-visible]:outline-3 data-[focus-visible]:outline-offset-2 data-[focus-visible]:outline-link";

function useSignInMessage() {
  const { t } = useLingui();
  return (error: unknown): string => {
    if (!(error instanceof ApiError)) return t`Something went wrong.`;
    if (error.status === 0) return t`The server cannot be reached.`;
    if (error.status === 429) return t`Too many attempts. Wait a minute and try again.`;
    if (error.status === 403 && error.code === "scope_too_low") {
      return t`This key can only read. Sign in with a key that has print or admin scope.`;
    }
    if (error.status === 401 && error.code === "bootstrap_disabled") {
      return t`The bootstrap key no longer works because an admin key exists. Sign in with that key.`;
    }
    if (error.status === 401) return t`That key was not accepted.`;
    return t`Something went wrong.`;
  };
}

/**
 * One field for an API key with `print` or `admin` scope (spec 8.1). The key is cleared
 * the moment it is sent and never stored in the browser.
 */
export function SignIn({ onSignIn }: { onSignIn: (key: string) => Promise<void> }) {
  const { t, i18n } = useLingui();
  const messageFor = useSignInMessage();
  const [key, setKey] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (key === "" || busy) return;
    const sent = key;
    setKey("");
    setError(null);
    setBusy(true);
    try {
      await onSignIn(sent);
    } catch (failure) {
      setError(messageFor(failure));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="grid min-h-dvh place-items-center p-4">
      <form
        onSubmit={(event) => void submit(event)}
        className="flex w-full max-w-sm flex-col gap-5 rounded-r3 border border-line bg-surface p-6"
      >
        <div>
          <h1>
            {/* The wordmark file draws in currentColor, which an <img> cannot inherit; as a mask it takes the
                ink colour of the active theme (light, dark or forced colours). */}
            <span role="img" aria-label={i18n._(messages.appName)} className="brand-wordmark block h-8 w-[125px]" />
          </h1>
          <p className="mt-2 text-ink-2">{i18n._(messages.tagline)}</p>
          <p className="mt-4">{t`Sign in with an API key that has print or admin scope.`}</p>
        </div>
        <TextField value={key} onChange={setKey} name="api-key" type="password" autoComplete="off" className="flex flex-col gap-1.5">
          <Label className="font-bold">{t`API key`}</Label>
          <Input className={`${FIELD} font-mono`} spellCheck={false} autoCapitalize="none" autoCorrect="off" />
        </TextField>
        {error ? (
          <p role="alert" className="flex items-start gap-2 text-bad">
            <svg viewBox="0 0 10 10" width="10" height="10" className="mt-2 shrink-0 fill-current" aria-hidden="true" data-shape="dot">
              <circle cx="5" cy="5" r="5" />
            </svg>
            <span className="text-ink">{error}</span>
          </p>
        ) : null}
        <Button type="submit" isDisabled={busy} className={PRIMARY_BUTTON}>
          {t`Sign in`}
        </Button>
        <p className="text-small">
          <SourceLink />
        </p>
      </form>
    </main>
  );
}
