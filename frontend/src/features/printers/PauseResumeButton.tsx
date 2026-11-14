// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useLingui } from "@lingui/react/macro";
import { Button } from "react-aria-components";
import { PRIMARY_BUTTON } from "../../shell/SignIn";
import { SECONDARY_BUTTON } from "../ui";
import { usePauseResume, type Printer } from "./api";

/**
 * Pause (secondary: it stops work) or Resume (primary: it is the way forward).
 * `named` adds the printer to the accessible name for lists with several of them.
 */
export function PauseResumeButton({ printer, named = false }: { printer: Printer; named?: boolean }) {
  const { t } = useLingui();
  const mutation = usePauseResume();
  const action = printer.paused ? "resume" : "pause";
  const label = printer.paused ? t`Resume` : t`Pause`;
  return (
    <span className="inline-flex flex-col items-start gap-1">
      <Button
        className={printer.paused ? PRIMARY_BUTTON : SECONDARY_BUTTON}
        isDisabled={mutation.isPending}
        aria-label={named ? `${label} ${printer.name}` : undefined}
        onPress={() => mutation.mutate({ id: printer.id, action })}
      >
        {label}
      </Button>
      {mutation.isError && (
        <span role="alert" className="text-small text-bad">
          {printer.paused ? t`Could not resume the printer.` : t`Could not pause the printer.`}
        </span>
      )}
    </span>
  );
}
