// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useLingui } from "@lingui/react/macro";
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Button, Label, Radio, RadioGroup } from "react-aria-components";
import { ApiError } from "../../../api/client";
import { PRIMARY_BUTTON, SECONDARY_BUTTON } from "../../ui";
import { capabilitiesKey, usePrintLoadingTest, useSetTrayLoading } from "../api";
import { useSheetErrorText } from "../errors";
import { loadingFromAnswers } from "./loading";

const RADIO =
  "group flex min-h-11 cursor-pointer items-center gap-3 rounded-r2 px-1 data-[focus-visible]:outline-3 data-[focus-visible]:outline-offset-2 data-[focus-visible]:outline-link";

function YesNo({ label, value, onChange }: { label: string; value: "yes" | "no" | null; onChange: (v: "yes" | "no") => void }) {
  const { t } = useLingui();
  return (
    <RadioGroup value={value} onChange={(v) => onChange(v as "yes" | "no")} className="flex flex-col gap-1">
      <Label className="font-bold text-ink">{label}</Label>
      <div className="flex flex-wrap gap-x-6">
        {(["yes", "no"] as const).map((v) => (
          <Radio key={v} value={v} className={RADIO}>
            <span aria-hidden="true" className="flex size-5 items-center justify-center rounded-full border-2 border-line-strong bg-sunken group-data-[selected]:border-accent">
              <span className="size-2.5 scale-0 rounded-full bg-accent transition-transform duration-150 ease-out group-data-[selected]:scale-100" />
            </span>
            <span>{v === "yes" ? t`Yes` : t`No`}</span>
          </Radio>
        ))}
      </div>
    </RadioGroup>
  );
}

/**
 * The guided test of how a tray takes paper (#350, R-350-5): mark a cross on the face-up side next to
 * the edge that goes in first, print the test page, answer two questions. The answer is stored for the
 * tray; a print key may store it once, so a 409 means someone else already did and the stored one is read.
 */
export function TrayLoadingTest({
  printerId,
  trayKey,
  trayLabel,
  onSaved,
}: {
  printerId: string;
  trayKey: string;
  trayLabel: string;
  onSaved?: () => void;
}) {
  const { t } = useLingui();
  const client = useQueryClient();
  const errorText = useSheetErrorText();
  const print = usePrintLoadingTest();
  const save = useSetTrayLoading();
  const [crossed, setCrossed] = useState<"yes" | "no" | null>(null);
  const [top, setTop] = useState<"yes" | "no" | null>(null);
  const [alreadySet, setAlreadySet] = useState(false);
  const printed = print.isSuccess;

  function submit() {
    if (crossed === null || top === null) return;
    save.mutate(
      { printerId, tray: trayKey, loading: loadingFromAnswers(crossed === "yes", top === "yes") },
      {
        onSuccess: () => onSaved?.(),
        onError: (error) => {
          if (error instanceof ApiError && error.code === "tray_loading_already_set") {
            setAlreadySet(true);
            void client.invalidateQueries({ queryKey: capabilitiesKey(printerId) });
            onSaved?.();
          }
        },
      },
    );
  }

  const saveError = save.isError && !alreadySet ? save.error : null;
  return (
    <section aria-labelledby="loading-test-h" className="flex flex-col gap-4 rounded-r3 border border-line bg-surface p-4">
      <h3 id="loading-test-h" className="font-bold">{t`How does this tray take paper?`}</h3>
      <ol className="m-0 flex list-decimal flex-col gap-1 pl-5 text-ink-2">
        <li>{t`Take a plain sheet and mark a cross on the side facing up, next to the edge that goes in first.`}</li>
        <li className="[overflow-wrap:anywhere]">{t`Put it into ${trayLabel} and print the test page.`}</li>
        <li>{t`Look where the print and the word “TOP” landed.`}</li>
      </ol>
      <div className="flex flex-wrap items-center gap-3">
        <Button onPress={() => print.mutate({ printerId, tray: trayKey })} isDisabled={print.isPending} className={printed ? SECONDARY_BUTTON : PRIMARY_BUTTON}>
          {printed ? t`Print the test page again` : t`Print test page`}
        </Button>
        <span role="status" className="text-small text-ink-2">
          {print.isPending ? t`Sending…` : printed ? t`The test page is in the print queue.` : null}
        </span>
      </div>
      {print.isError ? <p role="alert" className="font-bold text-bad">{errorText(print.error, t`The test page could not be printed.`)}</p> : null}
      {printed || alreadySet ? (
        <div className="flex flex-col gap-4">
          <YesNo label={t`Is the print on the side with the cross?`} value={crossed} onChange={setCrossed} />
          <YesNo label={t`Is “TOP” next to the cross?`} value={top} onChange={setTop} />
          <div className="flex flex-wrap items-center gap-3">
            <Button onPress={submit} isDisabled={crossed === null || top === null || save.isPending} className={PRIMARY_BUTTON}>
              {t`Save for this tray`}
            </Button>
            {alreadySet ? <span role="status" className="text-small text-ink-2">{t`Someone already set this tray; the stored answer is used.`}</span> : null}
          </div>
          {saveError ? <p role="alert" className="font-bold text-bad">{errorText(saveError, t`The answer could not be saved.`)}</p> : null}
        </div>
      ) : null}
    </section>
  );
}
