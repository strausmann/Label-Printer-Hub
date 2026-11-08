import { useLingui } from "@lingui/react/macro";
import { useState } from "react";
import { Button } from "react-aria-components";
import { PRIMARY_BUTTON } from "../../shell/SignIn";
import { StatusBadge } from "../../shell/StatusBadge";
import { PANEL, SECONDARY_BUTTON } from "../ui";
import { useAdminPrinters, usePrinterAdmin, type AdminPrinter } from "./api";
import { useErrorText } from "./feedback";
import { PrinterForm } from "./PrinterForm";
import { Section } from "./sections";

export function Printers() {
  const { t } = useLingui();
  const errorText = useErrorText();
  const printers = useAdminPrinters();
  const admin = usePrinterAdmin();
  const [restartNote, setRestartNote] = useState(false);
  const [editing, setEditing] = useState<AdminPrinter | "new" | null>(null);

  return (
    <Section title={t`Printers`} intro={t`Printers live here; there is no configuration file. A disabled printer keeps its history but receives no jobs.`}>
      {editing ? (
        <PrinterForm key={editing === "new" ? "new" : editing.slug} printer={editing === "new" ? null : editing} onDone={(result) => {
            setEditing(null);
            setRestartNote(result?.restartNote ?? false);
          }}
        />
      ) : (
        <div>
          <Button onPress={() => {
              setRestartNote(false);
              setEditing("new");
            }} className={PRIMARY_BUTTON}>
            {t`Add printer`}
          </Button>
        </div>
      )}

      {restartNote ? (
        <p role="status" className={`${PANEL} font-bold`}>
          {t`The printer is ready after the hub restarts.`}
        </p>
      ) : null}

      {printers.isPending ? (
        <p role="status" className="text-ink-2">{t`Loading…`}</p>
      ) : printers.isError ? (
        <p role="alert">{t`The printers could not be loaded.`}</p>
      ) : printers.data.length === 0 ? (
        <p className="text-ink-2">{t`No printers yet.`}</p>
      ) : (
        <ul className="grid gap-2">
          {printers.data.map((printer) => {
            const address =
              printer.backend === "ipp"
                ? String((printer.connection as { uri?: unknown }).uri ?? "")
                : `${String((printer.connection as { host?: unknown }).host ?? "")}:${String((printer.connection as { port?: unknown }).port ?? "")}`;
            return (
              <li key={printer.id} className={`${PANEL} flex flex-wrap items-center gap-x-6 gap-y-3`}>
                <div className="min-w-48 flex-1">
                  <div className="font-bold">{printer.name}</div>
                  <div className="text-small text-ink-2">
                    {printer.model ? `${printer.model} · ` : ""}
                    <span className="font-mono break-all">{address}</span>
                  </div>
                </div>
                <StatusBadge state={printer.enabled ? "ok" : "idle"} label={printer.enabled ? t`Enabled` : t`Disabled`} />
                <div className="flex gap-2">
                  <Button aria-label={t`Edit ${printer.name}`} onPress={() => {
                      setRestartNote(false);
                      setEditing(printer);
                    }} className={SECONDARY_BUTTON}>
                    {t`Edit`}
                  </Button>
                  <Button
                    aria-label={printer.enabled ? t`Disable ${printer.name}` : t`Enable ${printer.name}`}
                    isDisabled={admin.toggle.isPending}
                    onPress={() =>
                      admin.toggle.mutate(
                        { slug: printer.slug, enable: !printer.enabled },
                        { onSuccess: () => setRestartNote(printer.backend === "ipp") },
                      )
                    }
                    className={SECONDARY_BUTTON}
                  >
                    {printer.enabled ? t`Disable` : t`Enable`}
                  </Button>
                </div>
              </li>
            );
          })}
        </ul>
      )}
      {admin.toggle.isError ? <p role="alert">{errorText(admin.toggle.error, t`The printer could not be changed.`)}</p> : null}
    </Section>
  );
}
