import { useLingui } from "@lingui/react/macro";
import { useState } from "react";
import { Button, Radio, RadioGroup } from "react-aria-components";
import { SECONDARY_BUTTON } from "../ui";
import { useProbeIpp, type AdminPrinter, type IppProbeSummary, type TrayIn } from "./api";
import { HINT, LABEL, SwitchField, TextInput } from "./controls";
import { useErrorText } from "./feedback";

/** The server's field caps, mirrored so the form says no before the request does. */
export const URI_MAX = 1023;
export const TRAY_LABEL_MAX = 60;
export const LOAD_HINT_MAX = 200;
/** A page printer holds one to sixteen trays, the automatic choice included. */
export const TRAYS_MAX = 16;
const AUTO = "auto";
const SCHEMES = new Set(["ipp", "ipps", "http", "https"]);

export interface TrayDraft {
  key: string;
  label: string;
  loadHint: string;
  enabled: boolean;
  isDefault: boolean;
}

export type UriProblem = "empty" | "too_long" | "scheme" | "userinfo" | "invalid";

/** What is wrong with an address before it is sent (spec 11.1): scheme, user info, length. Null when it is fine. */
export function uriProblem(raw: string): UriProblem | null {
  const uri = raw.trim();
  if (uri === "") return "empty";
  if (uri.length > URI_MAX) return "too_long";
  const parts = /^([a-z][a-z0-9+.-]*):\/\/([^/?#]*)/i.exec(uri);
  if (!parts || !SCHEMES.has(parts[1]!.toLowerCase())) return "scheme";
  if (parts[2]!.includes("@")) return "userinfo";
  try {
    return new URL(uri).hostname === "" ? "invalid" : null;
  } catch {
    return "invalid";
  }
}

export type TrayProblem = "none_enabled" | "label" | "no_default" | "default_disabled";

/** The tray rules: at least one tray enabled, a label each, exactly one default and it enabled. */
export function trayProblem(trays: TrayDraft[]): TrayProblem | null {
  if (!trays.some((tray) => tray.enabled)) return "none_enabled";
  if (trays.some((tray) => tray.label.trim() === "")) return "label";
  const defaults = trays.filter((tray) => tray.isDefault);
  if (defaults.length !== 1) return "no_default";
  return defaults[0]!.enabled ? null : "default_disabled";
}

/**
 * Keeps the default on an enabled tray: when the default tray is switched off (or none is set), the first
 * enabled tray takes over. With nothing enabled the list is left alone and the rule shows as a message.
 */
export function settleDefault(trays: TrayDraft[]): TrayDraft[] {
  if (trays.some((tray) => tray.isDefault && tray.enabled)) return trays;
  const first = trays.find((tray) => tray.enabled);
  return first ? trays.map((tray) => ({ ...tray, isDefault: tray === first })) : trays;
}

const newTray = (key: string): TrayDraft => ({ key, label: key, loadHint: "", enabled: true, isDefault: false });

export const trayDraftsOf = (printer: AdminPrinter | null): TrayDraft[] =>
  (printer?.trays ?? []).map((tray) => ({
    key: tray.key,
    label: tray.label,
    loadHint: tray.load_hint ?? "",
    enabled: tray.enabled,
    isDefault: tray.is_default,
  }));

/**
 * The tray list after a probe: the printer's reported trays plus `auto` (always last), keeping what the
 * admin already set for a key. At most sixteen; `reported` says how many the printer named.
 */
export function mergeTrays(existing: TrayDraft[], sources: string[]): { trays: TrayDraft[]; reported: number } {
  const keys = [...new Set(sources.filter((key) => key !== AUTO))];
  const kept = keys.slice(0, TRAYS_MAX - 1);
  const byKey = new Map(existing.map((tray) => [tray.key, tray]));
  const trays = [...kept, AUTO].map((key) => byKey.get(key) ?? newTray(key));
  return { trays: settleDefault(trays), reported: keys.length };
}

export const trayPayload = (trays: TrayDraft[]): TrayIn[] =>
  trays.map((tray) => ({
    key: tray.key,
    label: tray.label.trim(),
    load_hint: tray.loadHint.trim() === "" ? null : tray.loadHint.trim(),
    enabled: tray.enabled,
    is_default: tray.isDefault,
  }));

const connectionOf = (printer: AdminPrinter | null) => (printer?.connection ?? {}) as { uri?: string; tls_verify?: boolean };

export function useIppDraft(printer: AdminPrinter | null) {
  const stored = connectionOf(printer);
  const probe = useProbeIpp();
  const [uri, setUriState] = useState(stored.uri ?? "");
  const [tlsVerify, setTlsVerifyState] = useState(stored.tls_verify ?? true);
  const [enabled, setEnabled] = useState(printer?.enabled ?? true);
  // A stored page printer without trays still shows the automatic one, so the table is never invisible.
  const [trays, setTrays] = useState<TrayDraft[]>(() => {
    const stored = trayDraftsOf(printer);
    return printer?.backend === "ipp" && stored.length === 0 ? mergeTrays([], []).trays : stored;
  });
  const [probed, setProbed] = useState<{ uri: string; tls: boolean; summary: IppProbeSummary } | null>(null);
  const [reported, setReported] = useState(0);

  const trimmed = uri.trim();
  const unchanged = printer !== null && trimmed === (stored.uri ?? "") && tlsVerify === (stored.tls_verify ?? true);
  const verified = unchanged || (probed !== null && probed.uri === trimmed && probed.tls === tlsVerify);
  const problem = uriProblem(uri);

  return {
    uri,
    setUri: (value: string) => {
      setUriState(value);
      probe.reset();
    },
    tlsVerify,
    setTlsVerify: (value: boolean) => {
      setTlsVerifyState(value);
      probe.reset();
    },
    enabled,
    setEnabled,
    trays,
    patchTray: (key: string, patch: Partial<TrayDraft>) =>
      setTrays((list) => settleDefault(list.map((tray) => (tray.key === key ? { ...tray, ...patch } : tray)))),
    setDefault: (key: string) => setTrays((list) => list.map((tray) => ({ ...tray, isDefault: tray.key === key }))),
    summary: probed && probed.uri === trimmed && probed.tls === tlsVerify ? probed.summary : null,
    reported,
    probe,
    problem,
    verified,
    runProbe: () => {
      if (problem !== null) return;
      probe.mutate(
        { uri: trimmed, tls_verify: tlsVerify },
        {
          onSuccess: (summary) => {
            setProbed({ uri: trimmed, tls: tlsVerify, summary });
            // Merge into the list as it is when the answer arrives, so edits made meanwhile survive.
            setTrays((list) => mergeTrays(list, summary.media_sources).trays);
            setReported(mergeTrays([], summary.media_sources).reported);
          },
        },
      );
    },
  };
}
export type IppDraft = ReturnType<typeof useIppDraft>;

export function useUriProblemText(): (problem: UriProblem | null) => string | null {
  const { t } = useLingui();
  return (problem) => {
    switch (problem) {
      case "scheme":
        return t`The address must start with ipp://, ipps://, http:// or https://.`;
      case "userinfo":
        return t`The address must not contain a user name or password.`;
      case "too_long":
        return t`The address can be at most 1023 characters.`;
      case "invalid":
        return t`That is not a valid address.`;
      default:
        return null;
    }
  };
}

export function useTrayProblemText(): (problem: TrayProblem | null) => string | null {
  const { t } = useLingui();
  return (problem) => {
    switch (problem) {
      case "none_enabled":
        return t`Enable at least one tray.`;
      case "label":
        return t`Every tray needs a label.`;
      case "no_default":
        return t`Choose one tray as the default.`;
      case "default_disabled":
        return t`The default tray must be one of the enabled trays.`;
      default:
        return null;
    }
  };
}

const CHIP = "rounded-r1 bg-surface px-2 py-1 font-mono text-small break-all";

/** A list of keywords as chips; long lists (40 media sizes) show the first few and a button for the rest. */
function Chips({ items, empty }: { items: string[]; empty: string }) {
  const { t } = useLingui();
  const [all, setAll] = useState(false);
  if (items.length === 0) return <span className="text-ink-2">{empty}</span>;
  const shown = all ? items : items.slice(0, 8);
  const count = items.length;
  return (
    <div className="flex min-w-0 flex-col items-start gap-2">
      <ul className="flex flex-wrap gap-1.5">
        {shown.map((item) => (
          <li key={item} className={CHIP}>
            {item}
          </li>
        ))}
      </ul>
      {items.length > shown.length ? (
        <Button onPress={() => setAll(true)} className={`${SECONDARY_BUTTON} h-11`}>
          {t`Show all ${count}`}
        </Button>
      ) : null}
    </div>
  );
}

const mm = (hundredths: number) => (hundredths / 100).toFixed(2);

function Summary({ summary }: { summary: IppProbeSummary }) {
  const { t } = useLingui();
  const margins = summary.margins_hmm;
  const [top, right, bottom, left] = margins ? [mm(margins.top), mm(margins.right), mm(margins.bottom), mm(margins.left)] : ["", "", "", ""];
  const dpi = summary.resolutions_dpi.join(", ");
  const row = "grid gap-1 sm:grid-cols-[11rem_1fr]";
  return (
    <section aria-label={t`What the printer reports`} className="flex min-w-0 flex-col gap-3 rounded-r2 bg-sunken p-4">
      <h4 className="font-bold">{t`What the printer reports`}</h4>
      <dl className="grid min-w-0 gap-3">
        <div className={row}>
          <dt className={LABEL}>{t`Make and model`}</dt>
          <dd className="min-w-0 break-words">{summary.make_and_model ?? t`Not reported`}</dd>
        </div>
        <div className={row}>
          <dt className={LABEL}>{t`PDF printing`}</dt>
          <dd>{summary.pdf_supported ? t`Yes` : t`No`}</dd>
        </div>
        <div className={row}>
          <dt className={LABEL}>{t`Resolutions`}</dt>
          <dd>{dpi ? t`${dpi} dpi` : t`Not reported`}</dd>
        </div>
        <div className={row}>
          <dt className={LABEL}>{t`Media sizes`}</dt>
          <dd className="min-w-0">
            <Chips items={summary.media_sizes} empty={t`Not reported`} />
          </dd>
        </div>
        <div className={row}>
          <dt className={LABEL}>{t`Media types`}</dt>
          <dd className="min-w-0">
            <Chips items={summary.media_types} empty={t`Not reported`} />
          </dd>
        </div>
        <div className={row}>
          <dt className={LABEL}>{t`Trays`}</dt>
          <dd className="min-w-0">
            <Chips items={summary.media_sources} empty={t`None reported, only the automatic choice`} />
          </dd>
        </div>
        <div className={row}>
          <dt className={LABEL}>{t`Colour modes`}</dt>
          <dd className="min-w-0">
            <Chips items={summary.color_modes} empty={t`Not reported`} />
          </dd>
        </div>
        <div className={row}>
          <dt className={LABEL}>{t`Unprintable margins`}</dt>
          <dd>
            {margins
              ? t`Top ${top} mm, right ${right} mm, bottom ${bottom} mm, left ${left} mm`
              : t`Not reported`}
          </dd>
        </div>
        <div className={row}>
          <dt className={LABEL}>{t`State`}</dt>
          <dd className="font-mono">{summary.state}</dd>
        </div>
      </dl>
      {summary.pdf_supported ? null : (
        <p role="note" className="font-bold">
          {t`This printer cannot print PDF, so the hub cannot use it for sheets.`}
        </p>
      )}
    </section>
  );
}

function TrayCard({ tray, draft }: { tray: TrayDraft; draft: IppDraft }) {
  const { t } = useLingui();
  return (
    <fieldset className="grid min-w-0 gap-3 rounded-r2 border border-line p-3">
      <legend className="px-1 font-mono text-small font-bold break-all">{tray.key}</legend>
      <div className="grid min-w-0 gap-3 sm:grid-cols-2">
        <TextInput label={t`Label`} value={tray.label} onChange={(label) => draft.patchTray(tray.key, { label })} maxLength={TRAY_LABEL_MAX} />
        <TextInput
          label={t`Load hint`}
          value={tray.loadHint}
          onChange={(loadHint) => draft.patchTray(tray.key, { loadHint })}
          maxLength={LOAD_HINT_MAX}
          placeholder={t`For example: face down`}
        />
      </div>
      <div className="flex flex-wrap items-center justify-between gap-x-6">
        <SwitchField label={t`Enabled: ${tray.key}`} isSelected={tray.enabled} onChange={(enabled) => draft.patchTray(tray.key, { enabled })} />
        <Radio
          value={tray.key}
          aria-label={t`Default: ${tray.key}`}
          className="group flex min-h-11 cursor-default items-center gap-2 rounded-r2 data-[focus-visible]:outline-3 data-[focus-visible]:outline-offset-2 data-[focus-visible]:outline-link"
        >
          <span
            aria-hidden="true"
            className="flex size-5 shrink-0 items-center justify-center rounded-full border-2 border-line-strong bg-sunken group-data-[selected]:border-accent"
          >
            <span className="size-2.5 scale-0 rounded-full bg-accent transition-transform duration-150 ease-out group-data-[selected]:scale-100" />
          </span>
          <span>{t`Default`}</span>
        </Radio>
      </div>
    </fieldset>
  );
}

/** The form part that belongs to a page printer: address, certificate, "Read printer", trays. */
export function IppPrinterFields({ draft }: { draft: IppDraft }) {
  const { t } = useLingui();
  const errorText = useErrorText();
  const uriText = useUriProblemText();
  const shownProblem = draft.uri.trim() === "" ? null : draft.problem;
  const listed = TRAYS_MAX - 1;
  const reported = draft.reported;
  const trayText = useTrayProblemText();
  const inlineProblem = trayText(trayProblem(draft.trays));
  const defaultKey = draft.trays.find((tray) => tray.isDefault)?.key ?? "";

  return (
    <>
      <TextInput
        label={t`IPP address`}
        value={draft.uri}
        onChange={draft.setUri}
        mono
        maxLength={URI_MAX}
        inputMode="url"
        invalid={shownProblem !== null}
        description={uriText(shownProblem) ?? t`For example ipp://printer.example.invalid:631/ipp/print`}
      />
      <SwitchField
        label={t`Verify the printer certificate`}
        isSelected={draft.tlsVerify}
        onChange={draft.setTlsVerify}
        description={draft.tlsVerify ? undefined : t`Warning: the certificate is not checked. Anyone on the network path could pose as the printer.`}
      />
      <div className="flex flex-wrap items-center gap-3">
        <Button onPress={draft.runProbe} isDisabled={draft.problem !== null || draft.probe.isPending} className={SECONDARY_BUTTON}>
          {t`Read printer`}
        </Button>
        {draft.probe.isPending ? <span role="status" className={HINT}>{t`Reading the printer…`}</span> : null}
      </div>
      {draft.probe.isError ? (
        <p role="alert" className="text-small text-ink">
          {errorText(draft.probe.error, t`The printer could not be read.`)}
        </p>
      ) : null}
      {draft.summary ? <Summary summary={draft.summary} /> : null}
      {!draft.verified && !draft.probe.isError && !draft.probe.isPending && draft.problem === null ? (
        <p className={HINT}>{t`Read the printer once before saving, so the hub knows its trays.`}</p>
      ) : null}
      {draft.trays.length > 0 ? (
        <div className="flex min-w-0 flex-col gap-3">
          <h4 className={LABEL}>{t`Trays`}</h4>
          <p className={HINT}>{t`Turn off the trays you do not use, and mark the one that should be used when none is chosen.`}</p>
          <RadioGroup aria-label={t`Default tray`} value={defaultKey} onChange={draft.setDefault} className="grid min-w-0 gap-3">
            {draft.trays.map((tray) => (
              <TrayCard key={tray.key} tray={tray} draft={draft} />
            ))}
          </RadioGroup>
          {inlineProblem ? (
            <p role="status" className="text-small font-bold text-ink">
              {inlineProblem}
            </p>
          ) : null}
          {draft.reported > TRAYS_MAX - 1 ? (
            <p className={HINT}>{t`Only the first ${listed} of ${reported} trays are listed.`}</p>
          ) : null}
        </div>
      ) : null}
      <SwitchField label={t`Printer enabled`} isSelected={draft.enabled} onChange={draft.setEnabled} />
    </>
  );
}
