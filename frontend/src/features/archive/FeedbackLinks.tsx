// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useLingui } from "@lingui/react/macro";
import { useState } from "react";
import { Button } from "react-aria-components";
import { useInfo } from "../../app/session";
import { PRIMARY_BUTTON } from "../../shell/SignIn";
import { ModalDialog } from "../settings/controls";
import { SECONDARY_BUTTON, SECTION_HEADING } from "../ui";
import { usePatchType, type SheetTypeDetail } from "./api";
import { useArchiveErrorText } from "./errors";
import { browserLabel, buildFeedbackUrl, type FeedbackKind } from "./feedbackLink";

/**
 * Two links that open a pre-filled GitHub issue about the dimensions of this type (#230), for every role,
 * and, for an admin, the separate and explicit action to mark the type as verified in this hub.
 * The links are plain anchors: following one changes nothing here.
 */
export function FeedbackLinks({ type, admin }: { type: SheetTypeDetail; admin: boolean }) {
  const { t } = useLingui();
  const errorText = useArchiveErrorText();
  const info = useInfo();
  const patch = usePatchType();
  const [confirming, setConfirming] = useState(false);

  const version = type.versions.find((v) => v.version === type.current_version);
  const hubVersion = info.data?.version;
  const href = (kind: FeedbackKind) =>
    version && hubVersion
      ? buildFeedbackUrl({
          kind,
          sheetType: type,
          version,
          hubVersion,
          scheme: window.location.protocol === "https:" ? "https" : "http",
          browser: browserLabel(navigator.userAgent),
        })
      : undefined;
  const report = href("wrong");
  const confirm = href("confirmed");
  // Until the hub version is known there is nothing honest to link to: show no section at all.
  if (!report || !confirm) return null;

  return (
    <section aria-labelledby="feedback-heading" className="flex flex-col gap-3">
      <h3 id="feedback-heading" className={SECTION_HEADING}>{t`Are these numbers right?`}</h3>
      <p className="max-w-prose text-ink-2">
        {t`Measured a sheet? Tell us what you found. The link opens a prepared issue on GitHub that holds this sheet type's data only: no address of your hub, no printer, no keys.`}
      </p>
      <div className="flex flex-wrap gap-3">
        <a href={report} target="_blank" rel="noopener noreferrer" className={`${SECONDARY_BUTTON} no-underline`}>
          {t`Report a problem with the dimensions`}
        </a>
        <a href={confirm} target="_blank" rel="noopener noreferrer" className={`${SECONDARY_BUTTON} no-underline`}>
          {t`Confirm the dimensions`}
        </a>
      </div>
      {admin && !type.verified ? (
        <div className="flex flex-wrap gap-3 border-t border-line pt-3">
          <Button onPress={() => setConfirming(true)} className={SECONDARY_BUTTON}>{t`Mark as verified locally`}</Button>
        </div>
      ) : null}
      {patch.error ? <p role="alert">{errorText(patch.error)}</p> : null}

      <ModalDialog title={t`Mark this type as verified?`} isOpen={confirming} onClose={() => setConfirming(false)} alert>
        <p>{t`Use this when you measured a sheet and the numbers match. It only marks ${type.key} as verified in this hub; nothing is sent to GitHub.`}</p>
        <div className="flex flex-wrap gap-3">
          <Button
            isDisabled={patch.isPending}
            onPress={() =>
              patch.mutate(
                { key: type.key, patch: { verified: true } },
                { onSettled: () => setConfirming(false) },
              )
            }
            className={PRIMARY_BUTTON}
          >
            {t`Mark as verified`}
          </Button>
          <Button onPress={() => setConfirming(false)} className={SECONDARY_BUTTON}>{t`Cancel`}</Button>
        </div>
      </ModalDialog>
    </section>
  );
}
