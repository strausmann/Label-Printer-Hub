import { useLingui } from "@lingui/react/macro";
import { useState } from "react";
import { Button } from "react-aria-components";
import { useInfo } from "../../app/session";
import { PRIMARY_BUTTON } from "../../shell/SignIn";
import { StatusBadge } from "../../shell/StatusBadge";
import { PANEL, SECONDARY_BUTTON } from "../ui";
import { useApiKeyAdmin, useApiKeys, useSaveSettings, type ApiKey, type SettingView } from "./api";
import { CheckboxChoices, ModalDialog, TextInput } from "./controls";
import { useSettingsDraft } from "./draft";
import { SaveFeedback, useErrorText } from "./feedback";
import { LastUsed } from "./LastUsed";
import { Section, WithSettings } from "./sections";
import { SettingField } from "./SettingField";

const SCOPES = ["read", "print", "admin"] as const;
const MIN_WEBHOOK_KEY = 32;

function randomKey(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(24));
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

/** The key as it was created: kept in this component's memory until the dialog is closed, never stored. */
function NewKeyDialog({ plaintext, onClose }: { plaintext: string | null; onClose: () => void }) {
  const { t } = useLingui();
  const [copy, setCopy] = useState<"idle" | "done" | "failed">("idle");
  async function copyKey() {
    try {
      await navigator.clipboard.writeText(plaintext ?? "");
      setCopy("done");
    } catch {
      setCopy("failed");
    }
  }
  return (
    <ModalDialog title={t`Your new key`} isOpen={plaintext !== null} onClose={onClose} dismissable={false}>
      <TextInput label={t`Key`} value={plaintext ?? ""} readOnly mono />
      <div className="flex items-center gap-3">
        <Button onPress={() => void copyKey()} className={SECONDARY_BUTTON}>
          {t`Copy key`}
        </Button>
        <span role="status" className="text-small text-ink-2">
          {copy === "done" ? t`Copied` : copy === "failed" ? t`Copy failed. Select the key and copy it by hand.` : ""}
        </span>
      </div>
      <p>{t`This key is shown only once. Store it in your password manager before you close this window.`}</p>
      <Button onPress={onClose} className={PRIMARY_BUTTON}>
        {t`Done`}
      </Button>
    </ModalDialog>
  );
}

function CreateKey({ onCreated }: { onCreated: (plaintext: string) => void }) {
  const { t } = useLingui();
  const errorText = useErrorText();
  const admin = useApiKeyAdmin();
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<string[]>(["read"]);
  const scopeOptions = SCOPES.map((id) => ({ id, label: id }));

  return (
    <form
      aria-label={t`Create an API key`}
      className={`${PANEL} flex max-w-xl flex-col gap-5`}
      onSubmit={(event) => {
        event.preventDefault();
        admin.create.mutate(
          { name: name.trim(), scopes },
          {
            onSuccess: (created) => {
              onCreated(created.plaintext);
              setName("");
              setScopes(["read"]);
            },
          },
        );
      }}
    >
      <TextInput label={t`Key name`} value={name} onChange={setName} description={t`A name that tells you who uses it, for example “Kept”.`} />
      <CheckboxChoices label={t`Scopes`} value={scopes} options={scopeOptions} onChange={setScopes} />
      <div>
        <Button type="submit" isDisabled={name.trim() === "" || scopes.length === 0 || admin.create.isPending} className={PRIMARY_BUTTON}>
          {t`Create key`}
        </Button>
      </div>
      {admin.create.isError ? <p role="alert">{errorText(admin.create.error, t`The key could not be created.`)}</p> : null}
    </form>
  );
}

function KeyList() {
  const { t } = useLingui();
  const errorText = useErrorText();
  const keys = useApiKeys();
  const admin = useApiKeyAdmin();
  const [revoking, setRevoking] = useState<ApiKey | null>(null);
  const revokingName = revoking?.name ?? "";

  if (keys.isPending) return <p role="status" className="text-ink-2">{t`Loading…`}</p>;
  if (keys.isError) return <p role="alert">{t`The keys could not be loaded.`}</p>;
  return (
    <>
      <ul className="grid gap-2">
        {keys.data.map((key) => (
          <li key={key.id} className={`${PANEL} flex flex-wrap items-center gap-x-6 gap-y-2`}>
            <div className="min-w-48 flex-1">
              <div className="font-bold">{key.name}</div>
              <div className="text-small text-ink-2">
                <span className="font-mono">{key.key_prefix}…</span> · <LastUsed at={key.last_used_at} />
              </div>
            </div>
            <span className="flex gap-2">
              {key.scopes.map((scope) => (
                <span key={scope} className="rounded-r1 bg-sunken px-2 py-0.5 text-small">
                  {scope}
                </span>
              ))}
            </span>
            {key.enabled ? (
              <Button aria-label={t`Revoke ${key.name}`} onPress={() => setRevoking(key)} className={SECONDARY_BUTTON}>
                {t`Revoke`}
              </Button>
            ) : (
              <StatusBadge state="idle" label={t`Revoked`} />
            )}
          </li>
        ))}
      </ul>
      <ModalDialog title={t`Revoke this key?`} alert isOpen={revoking !== null} onClose={() => setRevoking(null)}>
        <p>{t`${revokingName} stops working at once, and so does every browser session that signed in with it. This cannot be undone.`}</p>
        <div className="flex gap-3">
          <Button
            onPress={() => {
              if (revoking) admin.revoke.mutate(revoking.id, { onSettled: () => setRevoking(null) });
            }}
            className={PRIMARY_BUTTON}
          >
            {t`Revoke key`}
          </Button>
          <Button onPress={() => setRevoking(null)} className={SECONDARY_BUTTON}>
            {t`Keep it`}
          </Button>
        </div>
      </ModalDialog>
      {admin.revoke.isError ? <p role="alert">{errorText(admin.revoke.error, t`The key could not be revoked.`)}</p> : null}
    </>
  );
}

const WEBHOOK_KEY = "access.webhook_api_key";

function WebhookKey() {
  return <WithSettings>{(views) => <WebhookForm views={views} />}</WithSettings>;
}

function WebhookForm({ views }: { views: SettingView[] }) {
  const { t } = useLingui();
  const errorText = useErrorText();
  const save = useSaveSettings();
  const [generated, setGenerated] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const draft = useSettingsDraft(views);
  const view = draft.view(WEBHOOK_KEY);
  if (!view) return null;
  const value = draft.valueOf(WEBHOOK_KEY);
  const typed = typeof value === "string" ? value : "";
  const tooShort = typed !== "" && typed.length < MIN_WEBHOOK_KEY;
  const { values } = draft.payload([WEBHOOK_KEY]);
  const changed = WEBHOOK_KEY in values;

  return (
    <form
      className="flex max-w-xl flex-col gap-4"
      onSubmit={(event) => {
        event.preventDefault();
        setSaved(false);
        save.mutate(values, {
          onSuccess: () => {
            draft.clear([WEBHOOK_KEY]);
            // "Cannot be shown again" has to be true: drop the generated key (it also lives
            // in this component's state only, so leaving the page drops it as well).
            setGenerated(null);
            setSaved(true);
          },
        });
      }}
    >
      <SettingField
        view={view}
        label={t`Webhook key`}
        value={value}
        onChange={(next) => {
          setSaved(false);
          setGenerated(null);
          draft.set(WEBHOOK_KEY, next);
        }}
        description={tooShort ? t`A webhook key needs at least ${MIN_WEBHOOK_KEY} characters.` : t`Spoolman sends this key with its webhook. At least ${MIN_WEBHOOK_KEY} characters.`}
        mono
      />
      {!view.locked ? (
        <div className="flex flex-col gap-2">
          <Button
            onPress={() => {
              const key = randomKey();
              setGenerated(key);
              setSaved(false);
              draft.set(WEBHOOK_KEY, key);
            }}
            className={`${SECONDARY_BUTTON} self-start`}
          >
            {t`Generate a key`}
          </Button>
          {generated ? (
            <p className="text-small text-ink-2">
              {t`Copy it now; after saving it cannot be shown again:`} <code className="break-all font-mono text-ink">{generated}</code>
            </p>
          ) : null}
        </div>
      ) : null}
      {view.locked ? null : (
        <div>
          <Button type="submit" isDisabled={!changed || tooShort || save.isPending} className={PRIMARY_BUTTON}>
            {t`Save webhook key`}
          </Button>
        </div>
      )}
      <SaveFeedback error={save.isError ? errorText(save.error) : null} saved={saved} />
    </form>
  );
}

function SsoStatus() {
  const { t } = useLingui();
  const configured = useInfo().data?.auth.sso_configured ?? false;
  return (
    <div className="flex flex-wrap items-center gap-3">
      <StatusBadge state={configured ? "ok" : "idle"} label={configured ? t`Configured` : t`Not configured`} />
      <p className="text-ink-2">
        {configured
          ? t`Sign-in through a reverse proxy is configured. It is set by the container and cannot be changed here.`
          : t`Sign-in through a reverse proxy is not configured. Browsers sign in with an API key.`}
      </p>
    </div>
  );
}

export function AccessKeys() {
  const { t } = useLingui();
  const [plaintext, setPlaintext] = useState<string | null>(null);
  return (
    <div className="flex flex-col gap-10">
      <Section title={t`API keys`} intro={t`A key opens the API and the browser sign-in. read looks, print also prints, admin also changes settings.`}>
        <CreateKey onCreated={setPlaintext} />
        <KeyList />
        <NewKeyDialog plaintext={plaintext} onClose={() => setPlaintext(null)} />
      </Section>
      <Section title={t`Webhooks`} intro={t`The key that webhooks from other apps must present.`}>
        <WebhookKey />
      </Section>
      <Section title={t`Single sign-on`}>
        <SsoStatus />
      </Section>
    </div>
  );
}
