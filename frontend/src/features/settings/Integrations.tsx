import { Trans, useLingui } from "@lingui/react/macro";
import { Link } from "@tanstack/react-router";
import { useState } from "react";
import { Button } from "react-aria-components";
import { PRIMARY_BUTTON } from "../../shell/SignIn";
import { StatusBadge } from "../../shell/StatusBadge";
import { PANEL, SECONDARY_BUTTON } from "../ui";
import { useApiKeys, useSaveSettings, useTestIntegration, type ApiKey, type IntegrationTestResult, type SettingView } from "./api";
import { useInfo } from "../../app/session";
import { sameUrl, useSettingsDraft } from "./draft";
import { LastUsed } from "./LastUsed";
import { SaveFeedback, useErrorText } from "./feedback";
import { SettingField } from "./SettingField";
import { Section, WithSettings } from "./sections";

type Integration = "snipeit" | "grocy" | "spoolman" | "paperless";
const SECRET_SUFFIX: Record<Integration, string | null> = { snipeit: "api_key", grocy: "api_key", spoolman: null, paperless: "token" };
const NAMES: Record<Integration, string> = { snipeit: "Snipe-IT", grocy: "Grocy", spoolman: "Spoolman", paperless: "Paperless" };
const ORDER: Integration[] = ["paperless", "snipeit", "grocy", "spoolman"];

const isRedirect = (status: number | null | undefined): boolean => status != null && status >= 300 && status < 400;

/** The probe's detail, unless it only repeats the status that is shown next to it ("HTTP 302 HTTP 302"). */
function distinctDetail(result: IntegrationTestResult): string | null {
  const detail = result.detail?.trim();
  if (!detail || (result.status != null && detail === `HTTP ${result.status}`)) return null;
  return detail;
}

function IntegrationCard({ name, views }: { name: Integration; views: SettingView[] }) {
  const { t } = useLingui();
  const errorText = useErrorText();
  const draft = useSettingsDraft(views);
  const save = useSaveSettings();
  const test = useTestIntegration(name);
  const info = useInfo().data?.integrations.find((i) => i.name === name);
  const [saved, setSaved] = useState(false);
  // What the last test ran against: a result only describes the configuration it tested.
  const [testedSignature, setTestedSignature] = useState<string | null>(null);

  const urlKey = `integrations.${name}.url`;
  const secretKey = SECRET_SUFFIX[name] ? `integrations.${name}.${SECRET_SUFFIX[name]}` : null;
  const timeoutKey = `integrations.${name}.timeout`;
  const keys = [urlKey, ...(secretKey ? [secretKey] : []), timeoutKey];
  const urlView = draft.view(urlKey);
  const secretView = secretKey ? draft.view(secretKey) : undefined;
  if (!urlView) return null;

  const urlNow = String(draft.valueOf(urlKey));
  const urlChanged = !urlView.locked && draft.isDirty(urlKey) && urlNow.trim() !== "" && !sameUrl(urlNow, String(urlView.value ?? ""));
  const secretRequired = Boolean(secretView && !secretView.locked && secretView.is_set && urlChanged && draft.valueOf(secretKey!) === "");

  const { values, invalid } = draft.payload(keys);
  const changed = Object.keys(values).length > 0;
  const savedInSettings = urlView.is_set && (!secretView || secretView.is_set);
  // One source with the sidebar: /api/info says whether the integration is usable (Paperless has no entry there).
  const configured = info ? info.configured : savedInSettings;
  const savedButUnusable = !configured && (urlView.is_set || Boolean(secretView?.is_set));
  // The probe uses URL, secret and timeout. A secret's value is not readable here, only that one is present.
  const signature = JSON.stringify([
    urlNow.trim().replace(/\/+$/, ""),
    String(draft.valueOf(timeoutKey)),
    Boolean(secretView?.is_set) || (secretKey !== null && ![null, ""].includes(draft.valueOf(secretKey) as string | null)),
  ]);
  // A result describes the configuration it tested, not whatever the form shows now (settings may refresh after a save elsewhere).
  const resultCurrent = testedSignature === signature;
  // A test still running for an older configuration neither blocks the button nor shows a result.
  const testing = test.isPending && resultCurrent;
  // The header says what is known. "Connected" and "Connection failed" come only from a test of the values
  // that are saved; a result for unsaved edits says nothing about the saved integration.
  const tested = test.isSuccess && !changed && resultCurrent ? test.data : null;
  const header: { state: "ok" | "bad" | "idle"; label: string } = tested
    ? tested.ok
      ? { state: "ok", label: t`Connected` }
      : { state: "bad", label: t`Connection failed` }
    : configured
      ? { state: "ok", label: t`Configured` }
      : { state: "idle", label: t`Not set up` };
  const label = (suffix: string) => ({ url: t`URL`, secret: SECRET_SUFFIX[name] === "token" ? t`Token` : t`API key`, timeout: t`Timeout (seconds)` })[suffix]!;

  const change = (key: string) => (value: string | boolean | null) => {
    setSaved(false);
    test.reset();
    draft.set(key, value);
  };

  const heading = `${name}-heading`;
  return (
    <div role="group" aria-labelledby={heading} className={`${PANEL} flex flex-col gap-5`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 id={heading} className="text-section font-bold">
          {NAMES[name]}
        </h3>
        <StatusBadge state={header.state} label={header.label} />
      </div>
      {savedButUnusable ? (
        <p className="max-w-xl text-small text-ink-2">
          {t`Saved values exist, but this integration cannot be used yet. A secret may belong to another URL or may not be readable with the current secret key, or the URL is missing. Enter the secret again.`}
        </p>
      ) : null}
      <div className="grid max-w-xl gap-5">
        <SettingField view={urlView} label={label("url")} value={draft.valueOf(urlKey)} onChange={change(urlKey)} />
        {secretView && secretKey ? (
          <SettingField view={secretView} label={label("secret")} value={draft.valueOf(secretKey)} onChange={change(secretKey)} required={secretRequired} />
        ) : null}
        {draft.view(timeoutKey) ? (
          <SettingField view={draft.view(timeoutKey)!} label={label("timeout")} value={draft.valueOf(timeoutKey)} onChange={change(timeoutKey)} />
        ) : null}
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Button
          onPress={() => {
            setTestedSignature(signature);
            test.mutate(values);
          }}
          isDisabled={testing || invalid.length > 0}
          className={SECONDARY_BUTTON}
        >
          {testing ? t`Testing…` : t`Test connection`}
        </Button>
        <Button
          isDisabled={!changed || invalid.length > 0 || secretRequired || save.isPending}
          onPress={() => {
            setSaved(false);
            save.mutate(values, {
              onSuccess: () => {
                draft.clear(keys);
                setSaved(true);
              },
            });
          }}
          className={PRIMARY_BUTTON}
        >
          {t`Save`}
        </Button>
      </div>
      {test.isPending || !resultCurrent ? null : test.isSuccess ? (
        <div role="status" className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <StatusBadge state={test.data.ok ? "ok" : "bad"} label={test.data.ok ? t`Works` : t`Failed`} />
          {test.data.ok ? null : (
            <>
              {test.data.status ? <span className="font-mono text-small text-ink-2">{t`HTTP ${test.data.status}`}</span> : null}
              {isRedirect(test.data.status) ? (
                <span className="text-ink">{t`The address redirects, often to a login page in front of the app. Use an address that reaches the app's API directly.`}</span>
              ) : distinctDetail(test.data) ? (
                <span className="text-ink">{distinctDetail(test.data)}</span>
              ) : null}
            </>
          )}
        </div>
      ) : test.isError ? (
        <p role="alert">{errorText(test.error, t`The test could not be run.`)}</p>
      ) : null}
      <SaveFeedback error={save.isError ? errorText(save.error) : null} saved={saved} />
    </div>
  );
}

/** Keys whose names identify a client of this hub (Kept, Hangar …); admin keys are not clients. */
const CLIENT_PATTERN = /kept|hangar|grocy|spoolman|paperless|snipe/i;

export const isClientKey = (key: ApiKey): boolean => key.enabled && CLIENT_PATTERN.test(key.name);

function ClientList() {
  const { t } = useLingui();
  const keys = useApiKeys();
  const clients = (keys.data ?? []).filter(isClientKey);
  return (
    <Section
      title={t`Clients`}
      label="Clients"
      intro={t`Other apps that print through this hub. They are recognised by the name of their API key.`}
    >
      {keys.isPending ? (
        <p role="status" className="text-ink-2">{t`Loading…`}</p>
      ) : clients.length === 0 ? (
        <p className="text-ink-2">
          <Trans>
            No client keys yet. Create one under{" "}
            <Link to="/settings/access" className="text-link underline underline-offset-2">
              Access and keys
            </Link>
            , named after the client (for example “Kept”).
          </Trans>
        </p>
      ) : (
        <ul className="grid gap-2">
          {clients.map((key) => (
            <li key={key.id} className={`${PANEL} flex flex-wrap items-center gap-x-6 gap-y-1`}>
              <span className="min-w-32 font-bold">{key.name}</span>
              <span className="flex gap-2">
                {key.scopes.map((scope) => (
                  <span key={scope} className="rounded-r1 bg-sunken px-2 py-0.5 text-small">
                    {scope}
                  </span>
                ))}
              </span>
              <span className="text-small text-ink-2">
                <LastUsed at={key.last_used_at} />
              </span>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

export function Integrations() {
  const { t } = useLingui();
  return (
    <div className="flex flex-col gap-10">
      <Section
        title={t`Integrations`}
        intro={t`Connect the apps that labels are made from. A secret belongs to the URL it was saved with: change the URL and you enter the secret again.`}
      >
        <WithSettings>
          {(views) => (
            <div className="grid gap-5 xl:grid-cols-2">
              {ORDER.map((name) => (
                <IntegrationCard key={name} name={name} views={views} />
              ))}
            </div>
          )}
        </WithSettings>
      </Section>
      <ClientList />
    </div>
  );
}
