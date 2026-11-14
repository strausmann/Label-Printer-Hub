// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useLingui } from "@lingui/react/macro";
import { useState } from "react";
import { Button } from "react-aria-components";
import { ApiError } from "../../api/client";
import { useSession } from "../../app/session";
import { ModalDialog } from "../settings/controls";
import { PRIMARY_BUTTON, SECONDARY_BUTTON } from "../ui";
import { useResolveIdentity, type IdentityResolution, type Printer } from "./api";

/** The words for the kind of a hardware identity (the server sends `serial`, `ipp_uuid` or `mac`). */
export function useIdentityKindLabel(): (kind: string | null | undefined) => string {
  const { t } = useLingui();
  return (kind) => {
    switch (kind) {
      case "serial":
        return t`Serial number`;
      case "ipp_uuid":
        return t`IPP UUID`;
      case "mac":
        return t`MAC address`;
      default:
        return kind ?? "";
    }
  };
}

type Problem = "changed" | "settled" | "denied" | "failed";

function problemOf(error: unknown): Problem {
  if (error instanceof ApiError) {
    if (error.code === "identity-changed") return "changed";
    if (error.code === "no-identity-mismatch") return "settled";
    if (error.status === 403) return "denied";
  }
  return "failed";
}

/** One identity as the admin compares it: its kind in words, then the value, which wraps at any character. */
function IdentityValue({ kind, value }: { kind: string | null | undefined; value: string }) {
  const kindLabel = useIdentityKindLabel();
  return (
    <>
      <span className="block text-ink-2">{kindLabel(kind)}</span>
      <span className="code block [overflow-wrap:anywhere]">{value}</span>
    </>
  );
}

/** What the page says once a swap turned out to be settled already: the banner is gone by then, so this stands on its own. */
export function SettledNotice() {
  const { t } = useLingui();
  return (
    <p role="status" className="rounded-r2 bg-sunken px-3 py-2 text-small">
      {t`Someone has settled this already. The page shows the current state.`}
    </p>
  );
}

/**
 * Shown at the top of a printer that answered as a different device than the one stored. Every key
 * is told, because sheet printing and the calibration page are held for everyone; only an admin sees
 * the two identities and can settle it. The server binds the decision to the identity shown here.
 */
export function IdentityMismatchBanner({ printer, onSettled }: { printer: Printer; onSettled: () => void }) {
  const { t } = useLingui();
  const admin = useSession().scope === "admin";
  const resolve = useResolveIdentity(printer.id);
  const [confirming, setConfirming] = useState(false);
  const [problem, setProblem] = useState<Exclude<Problem, "settled"> | null>(null);
  const observedId = printer.observed_id ?? null;
  const observedKind = printer.observed_kind ?? null;
  const storedId = printer.hardware_id ?? null;
  const canDecide = admin && observedId !== null && observedKind !== null;

  const send = (resolution: IdentityResolution) => {
    if (observedId === null || observedKind === null) return;
    setProblem(null);
    resolve.mutate(
      { resolution, expected_observed_id: observedId, expected_observed_kind: observedKind },
      {
        onSuccess: () => setConfirming(false),
        onError: (error) => {
          setConfirming(false);
          const found = problemOf(error);
          // "Settled already" ends the swap: the status refetch removes this banner, so the page says it.
          if (found === "settled") onSettled();
          else setProblem(found);
        },
      },
    );
  };

  const problemText: Record<Exclude<Problem, "settled">, string> = {
    changed: t`The device at this address changed while you were looking. Check the values shown now before you decide.`,
    denied: t`This key may not settle a device swap.`,
    failed: t`The decision could not be saved. Try again.`,
  };

  return (
    <section aria-label={t`Device swap`} className="flex min-w-0 flex-col gap-4 rounded-r3 border-2 border-warn bg-surface p-4">
      <div className="flex items-start gap-3">
        <svg viewBox="0 0 10 10" width="12" height="12" aria-hidden="true" focusable="false" className="mt-1.5 shrink-0 fill-current text-warn">
          <polygon points="5,0 10,5 5,10 0,5" />
        </svg>
        {/* Only the sentence is a live region: the identities and buttons below stay reachable, not announced. */}
        <p role="alert" className="min-w-0 font-bold">{t`Different device detected at this address. Sheet printing and the calibration page are held until an admin confirms.`}</p>
      </div>
      {canDecide && (
        <dl className="grid min-w-0 grid-cols-1 gap-3 text-small sm:grid-cols-2">
          <div className="min-w-0 rounded-r2 bg-sunken px-3 py-2">
            <dt className="font-bold">{t`Stored`}</dt>
            <dd>{storedId === null ? <span className="text-ink-2">—</span> : <IdentityValue kind={printer.hardware_id_kind} value={storedId} />}</dd>
          </div>
          <div className="min-w-0 rounded-r2 bg-sunken px-3 py-2">
            <dt className="font-bold">{t`Now at this address`}</dt>
            <dd>
              <IdentityValue kind={observedKind} value={observedId} />
            </dd>
          </div>
        </dl>
      )}
      {canDecide && (
        <div className="flex flex-wrap gap-2">
          <Button className={SECONDARY_BUTTON} isDisabled={resolve.isPending} onPress={() => send("same_device")}>
            {t`Same device`}
          </Button>
          <Button className={SECONDARY_BUTTON} isDisabled={resolve.isPending} onPress={() => setConfirming(true)}>
            {t`Device replaced`}
          </Button>
        </div>
      )}
      {problem !== null && <p role="alert" className="text-small font-bold text-bad">{problemText[problem]}</p>}
      {canDecide && (
        <ModalDialog title={t`Replace the device?`} isOpen={confirming} onClose={() => setConfirming(false)} alert>
          <p className="[overflow-wrap:anywhere]">
            {t`The calibration of every tray of this printer is reset, and the device now at this address is stored as the new one.`}
          </p>
          <div className="text-small">
            <IdentityValue kind={observedKind} value={observedId} />
          </div>
          <div className="flex flex-wrap justify-end gap-2">
            <Button className={SECONDARY_BUTTON} onPress={() => setConfirming(false)}>
              {t`Cancel`}
            </Button>
            <Button className={PRIMARY_BUTTON} isDisabled={resolve.isPending} onPress={() => send("replaced")}>
              {t`Reset calibration and accept`}
            </Button>
          </div>
        </ModalDialog>
      )}
    </section>
  );
}
