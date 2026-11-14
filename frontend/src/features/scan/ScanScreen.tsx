// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useLingui } from "@lingui/react/macro";
import { useRouter } from "@tanstack/react-router";
import { useCallback, useState } from "react";
import { Button } from "react-aria-components";
import { PRIMARY_BUTTON } from "../../shell/SignIn";
import { PANEL, SECONDARY_BUTTON } from "../ui";
import { CameraScanner } from "./CameraScanner";
import type { ScanHit } from "./decoder";
import { resolveScan } from "./resolvers";

export { setScanDeps, type ScanDeps } from "./CameraScanner";

function useCopy(text: string) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
    } catch {
      /* clipboard blocked: the code stays selectable on screen */
    }
  };
  return { copied, copy };
}

function UnknownCode({ hit, onAgain }: { hit: ScanHit; onAgain: () => void }) {
  const { t } = useLingui();
  const { copied, copy } = useCopy(hit.text);
  return (
    <section aria-labelledby="unknown-heading" className={`${PANEL} flex flex-col gap-3`}>
      <h2 id="unknown-heading" className="text-section font-bold">
        {t`Unknown code`}
      </h2>
      <p className="text-ink-2">{t`This code is not one the hub knows. Its text:`}</p>
      <code className="max-h-40 overflow-y-auto rounded-r2 bg-sunken p-3 font-semibold break-all select-text">{hit.text}</code>
      <div className="flex flex-wrap gap-2">
        <Button onPress={() => void copy()} className={SECONDARY_BUTTON}>
          {copied ? t`Copied` : t`Copy`}
        </Button>
        <Button onPress={onAgain} className={PRIMARY_BUTTON}>
          {t`Scan again`}
        </Button>
      </div>
    </section>
  );
}

/**
 * The scan screen (spec 5.3/5.4): the camera, the registered resolvers, and straight to where the
 * code leads. A code nobody knows is shown with its text.
 */
export function ScanScreen() {
  const { t } = useLingui();
  const router = useRouter();
  const [unknown, setUnknown] = useState<ScanHit | null>(null);

  /** A hit either leads somewhere (navigate) or is shown as an unknown code. */
  const handle = useCallback(
    (hit: ScanHit): void => {
      const resolution = resolveScan(hit);
      if (resolution) router.history.push(resolution.route);
      else setUnknown(hit);
    },
    [router],
  );

  return (
    <div className="mx-auto flex w-full max-w-xl flex-col gap-4">
      <h1 className="text-title font-bold">{t`Scan`}</h1>
      <CameraScanner onHit={handle} paused={unknown !== null}>
        {unknown && <UnknownCode key={unknown.text} hit={unknown} onAgain={() => setUnknown(null)} />}
      </CameraScanner>
    </div>
  );
}
