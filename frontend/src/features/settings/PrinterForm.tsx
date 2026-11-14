// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useLingui } from "@lingui/react/macro";
import { useState } from "react";
import { Button } from "react-aria-components";
import { PRIMARY_BUTTON } from "../../shell/SignIn";
import { LayoutPicker } from "../layout/LayoutPicker";
import { layoutDefaultFor, QL_WIDE_MM, type LayoutChoice } from "../layout/ql";
import { PANEL, SECONDARY_BUTTON } from "../ui";
import { usePrinterAdmin, type AdminPrinter, type PrinterCreate } from "./api";
import { SelectField, SwitchField, TextInput } from "./controls";
import { SaveFeedback, useErrorText } from "./feedback";
import { IppPrinterFields, trayPayload, trayProblem, useIppDraft, useTrayProblemText, useUriProblemText } from "./IppPrinterFields";

const SLUG = /^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$/;
const MODELS: Record<string, string[]> = { ptouch: ["PT-P750W"], brother_ql: ["QL-820NWB"] };

const connectionOf = (printer: AdminPrinter | null) => (printer?.connection ?? {}) as { host?: string; port?: number; snmp?: unknown };
const numberIn = (obj: Record<string, unknown> | undefined, key: string, fallback: number) => {
  const v = obj?.[key];
  return typeof v === "number" ? v : fallback;
};

/**
 * Add a printer or change one (D6). The slug, model and backend name the printer and
 * the driver, so they can only be chosen when it is created.
 */
export function PrinterForm({
  printer,
  onDone,
}: {
  printer: AdminPrinter | null;
  /** Called when the form closes. What was saved applies at once; the hub needs no restart. */
  onDone: () => void;
}) {
  const { t } = useLingui();
  const errorText = useErrorText();
  const uriText = useUriProblemText();
  const trayText = useTrayProblemText();
  const admin = usePrinterAdmin();
  const editing = printer !== null;
  const conn = connectionOf(printer);

  const [name, setName] = useState(printer?.name ?? "");
  const [slug, setSlug] = useState("");
  const [backend, setBackend] = useState(printer?.backend ?? "ptouch");
  const [model, setModel] = useState(printer?.model ?? MODELS.ptouch![0]!);
  const [host, setHost] = useState(conn.host ?? "");
  const [port, setPort] = useState(String(conn.port ?? 9100));
  const [timeout, setTimeoutValue] = useState(String(numberIn(printer?.queue, "timeout_s", 30)));
  const [halfCut, setHalfCut] = useState(Boolean(printer?.cut_defaults?.half_cut));
  const storedLayout = layoutDefaultFor(printer?.layout_defaults, QL_WIDE_MM);
  // The 62 mm default is only sent when it was touched: saving the form must not pin the tape default.
  const [layoutDraft, setLayoutDraft] = useState<LayoutChoice | null>(null);
  const layoutShown = layoutDraft ?? storedLayout;
  const ipp = useIppDraft(printer);
  const [formError, setFormError] = useState<string | null>(null);

  const isIpp = backend === "ipp";
  const isQl = backend === "brother_ql";
  const pending = admin.create.isPending || admin.update.isPending;
  const serverError = admin.create.error ?? admin.update.error;

  function submitIpp() {
    const timeoutNumber = Number(timeout);
    if (!name.trim()) return setFormError(t`The name is required.`);
    if (ipp.problem !== null) return setFormError(uriText(ipp.problem) ?? t`Enter the printer's address.`);
    if (!Number.isInteger(timeoutNumber) || timeoutNumber < 1 || timeoutNumber > 600) return setFormError(t`The queue timeout must be between 1 and 600 seconds.`);
    if (!editing && !SLUG.test(slug)) return setFormError(t`The slug uses lowercase letters, digits and dashes, 3 to 64 characters.`);
    if (!ipp.verified) return setFormError(t`Read the printer once before saving, so the hub knows its trays.`);
    const trayIssue = trayProblem(ipp.trays);
    if (trayIssue) return setFormError(trayText(trayIssue));
    setFormError(null);
    const connection = { uri: ipp.uri.trim(), tls_verify: ipp.tlsVerify };
    const queue = { timeout_s: timeoutNumber };
    const trays = trayPayload(ipp.trays);
    if (printer) {
      admin.update.mutate({ slug: printer.slug, body: { name: name.trim(), connection, queue, enabled: ipp.enabled, trays } }, { onSuccess: () => onDone() });
    } else {
      admin.create.mutate({ name: name.trim(), slug, backend: "ipp", connection, queue, enabled: ipp.enabled, trays }, { onSuccess: () => onDone() });
    }
  }

  function submit() {
    if (isIpp) return submitIpp();
    const portNumber = Number(port);
    const timeoutNumber = Number(timeout);
    if (!name.trim() || !host.trim()) return setFormError(t`Name and host are required.`);
    if (!Number.isInteger(portNumber) || portNumber < 1 || portNumber > 65535) return setFormError(t`The port must be between 1 and 65535.`);
    if (!Number.isInteger(timeoutNumber) || timeoutNumber < 1 || timeoutNumber > 600) return setFormError(t`The queue timeout must be between 1 and 600 seconds.`);
    if (!editing && !SLUG.test(slug)) return setFormError(t`The slug uses lowercase letters, digits and dashes, 3 to 64 characters.`);
    setFormError(null);
    const connection = { ...(conn as object), host: host.trim(), port: portNumber } as PrinterCreate["connection"];
    const queue = { timeout_s: timeoutNumber };
    // A QL printer always cuts fully: it has no half cut to default, so the form sends none (263-63).
    const cut_defaults = isQl ? undefined : { half_cut: halfCut };
    // PUT replaces the whole map: the other widths stay as they are stored.
    const layout_defaults =
      isQl && layoutDraft
        ? { ...(printer?.layout_defaults ?? {}), [String(QL_WIDE_MM)]: layoutDraft.orientation === "across" ? layoutDraft : { orientation: layoutDraft.orientation } }
        : undefined;
    if (printer) {
      admin.update.mutate({ slug: printer.slug, body: { name: name.trim(), connection, queue, cut_defaults, layout_defaults } }, { onSuccess: () => onDone() });
    } else {
      admin.create.mutate({ name: name.trim(), slug, model, backend: backend as PrinterCreate["backend"], connection, queue, cut_defaults, layout_defaults, enabled: true }, { onSuccess: () => onDone() });
    }
  }

  const heading = editing ? t`Edit ${printer.name}` : t`Add a printer`;
  return (
    <form
      aria-label={heading}
      className={`${PANEL} flex max-w-xl flex-col gap-5`}
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <h3 className="text-section font-bold">{heading}</h3>
      <TextInput label={t`Name`} value={name} onChange={setName} />
      {editing ? null : (
        <TextInput label={t`Slug`} value={slug} onChange={setSlug} mono description={t`The short name in addresses and in the API. It cannot be changed later.`} />
      )}
      {editing ? (
        printer.model ? (
          <p className="text-ink-2">
            {t`Model`}: <span className="font-bold text-ink">{printer.model}</span>
          </p>
        ) : null
      ) : (
        <div className="grid gap-5 sm:grid-cols-2">
          <SelectField
            label={t`Driver`}
            value={backend}
            options={[
              { id: "ptouch", label: "P-touch (PT)" },
              { id: "brother_ql", label: "Brother QL" },
              { id: "ipp", label: t`Page printer (IPP)` },
            ]}
            onChange={(next) => {
              setBackend(next);
              setModel(MODELS[next]?.[0] ?? "");
            }}
          />
          {isIpp ? null : <TextInput label={t`Model`} value={model} onChange={setModel} mono />}
        </div>
      )}
      {isIpp ? (
        <IppPrinterFields draft={ipp} />
      ) : (
        <div className="grid gap-5 sm:grid-cols-[1fr_8rem]">
          <TextInput label={t`Host`} value={host} onChange={setHost} mono />
          <TextInput label={t`Port`} value={port} onChange={setPort} mono inputMode="numeric" />
        </div>
      )}
      <TextInput label={t`Queue timeout (seconds)`} value={timeout} onChange={setTimeoutValue} inputMode="numeric" />
      {/* A QL printer always cuts fully; the half cut is a P-touch feature. */}
      {isIpp || isQl ? null : (
        <SwitchField
          label={t`Half cut by default`}
          isSelected={halfCut}
          onChange={setHalfCut}
          description={t`Cuts the tape but leaves the backing, so a strip of labels stays together. A print can still override it.`}
        />
      )}
      {isQl ? (
        <fieldset className="flex flex-col gap-3">
          <legend className="font-bold">{t`Label layout on 62 mm tape`}</legend>
          <p className="text-small text-ink-2">{t`What a print uses when it names no layout. The print dialog starts from this and can still change it.`}</p>
          <LayoutPicker
            orientation={layoutShown.orientation}
            preset={layoutShown.preset}
            onOrientation={(orientation) => setLayoutDraft({ ...layoutShown, orientation })}
            onPreset={(preset) => setLayoutDraft({ ...layoutShown, preset })}
          />
        </fieldset>
      ) : null}
      <div className="flex flex-wrap gap-3">
        <Button type="submit" isDisabled={pending || (isIpp && !ipp.verified)} className={PRIMARY_BUTTON}>
          {editing ? t`Save printer` : t`Create printer`}
        </Button>
        <Button onPress={() => onDone()} className={SECONDARY_BUTTON}>
          {t`Cancel`}
        </Button>
      </div>
      <SaveFeedback error={formError ?? (serverError ? errorText(serverError) : null)} saved={false} />
    </form>
  );
}
