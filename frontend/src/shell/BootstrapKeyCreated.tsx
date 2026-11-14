// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { Trans, useLingui } from "@lingui/react/macro";
import { useState } from "react";
import { Button, Input, Label, TextField } from "react-aria-components";
import { SourceLink } from "../features/about/SourceLink";
import { FIELD, PRIMARY_BUTTON } from "./SignIn";

const SECONDARY_BUTTON =
  "press inline-flex h-11 items-center justify-center rounded-r2 border border-line-strong bg-surface px-4 font-bold text-ink transition-colors duration-150 hover:bg-sunken data-[focus-visible]:outline-3 data-[focus-visible]:outline-offset-2 data-[focus-visible]:outline-link";

interface Props {
  /** Creates the first admin key and resolves to its plaintext (shown once). */
  onCreate: () => Promise<string>;
  /** Signs in with the new key; the bootstrap session ends once a real admin key exists (D7). */
  onContinue: (key: string) => Promise<void>;
}

/**
 * First sign-in with the one-time bootstrap key: the only thing it can do is create the
 * first admin key. The key is shown once, then the hub asks to remove the bootstrap variable.
 */
export function BootstrapKeyCreated({ onCreate, onContinue }: Props) {
  const { t } = useLingui();
  const [key, setKey] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copy, setCopy] = useState<"idle" | "done" | "failed">("idle");

  async function create() {
    setBusy(true);
    setError(null);
    try {
      setKey(await onCreate());
    } catch {
      setError(t`The key could not be created.`);
    } finally {
      setBusy(false);
    }
  }

  async function proceed(value: string) {
    setBusy(true);
    setError(null);
    try {
      await onContinue(value);
    } catch {
      setError(t`Signing in with the new key failed.`);
      setBusy(false);
    }
  }

  async function copyKey(value: string) {
    try {
      await navigator.clipboard.writeText(value);
      setCopy("done");
    } catch {
      setCopy("failed");
    }
  }

  return (
    <main className="grid min-h-dvh place-items-center p-4">
      <section className="flex w-full max-w-lg flex-col gap-5 rounded-r3 border border-line bg-surface p-6">
        <div>
          <h1 className="text-title font-bold">{t`Create the first admin key`}</h1>
          <p className="mt-1 text-ink-2">
            {t`You signed in with the one-time bootstrap key. It can do one thing: create the first admin key.`}
          </p>
        </div>

        {key === null ? (
          <Button onPress={() => void create()} isDisabled={busy} className={PRIMARY_BUTTON}>
            {t`Create admin key`}
          </Button>
        ) : (
          <>
            <TextField value={key} isReadOnly className="flex flex-col gap-1.5">
              <Label className="font-bold">{t`Your new admin key`}</Label>
              <Input className={`${FIELD} font-mono`} onFocus={(event) => event.currentTarget.select()} />
            </TextField>
            <div className="flex items-center gap-3">
              <Button onPress={() => void copyKey(key)} className={SECONDARY_BUTTON}>
                {t`Copy key`}
              </Button>
              <span role="status" className="text-small text-ink-2">
                {copy === "done" ? t`Copied` : copy === "failed" ? t`Copy failed. Select the key and copy it by hand.` : ""}
              </span>
            </div>
            <p>{t`This key is shown only once. Store it in your password manager before you continue.`}</p>
            <p>
              <Trans>
                Remove <code>LABELYARD_BOOTSTRAP_ADMIN_KEY</code> from the container; it no longer works once this key exists.
              </Trans>
            </p>
            <Button onPress={() => void proceed(key)} isDisabled={busy} className={PRIMARY_BUTTON}>
              {t`Continue`}
            </Button>
          </>
        )}

        {error ? (
          <p role="alert" className="text-ink">
            {error}
          </p>
        ) : null}
        <p className="text-small">
          <SourceLink />
        </p>
      </section>
    </main>
  );
}
