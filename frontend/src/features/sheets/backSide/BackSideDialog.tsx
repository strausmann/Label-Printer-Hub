// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useLingui } from "@lingui/react/macro";
import { useSheetType } from "../../archive/api";
import { ModalDialog } from "../../settings/controls";
import { useSheet } from "../api";
import { pageSizeMm } from "../cellState";
import { ActivateBackSide } from "./ActivateBackSide";

/**
 * "Print back side" for a sheet that exists (#350): the sheet page, and the print result of a sheet the
 * print dialog started. Reads the sheet and its type for the strip, then runs the activation steps.
 */
export function BackSideDialog({
  code,
  isOpen,
  onClose,
  printerId,
  title,
}: {
  code: string;
  isOpen: boolean;
  onClose: () => void;
  printerId?: string;
  /** The dialog's title; left out: "Activate new sheet" (the print result of a sheet the print dialog started). */
  title?: string;
}) {
  const { t } = useLingui();
  const sheet = useSheet(code);
  const type = useSheetType(sheet.data?.type_key ?? "", isOpen && !!sheet.data);
  const ready = sheet.data && type.data;
  return (
    <ModalDialog title={title ?? t`Activate new sheet`} isOpen={isOpen} onClose={onClose} wide>
      {ready ? (
        <ActivateBackSide
          target={{ kind: "existing", code }}
          codeLabel={code}
          typeLabel={sheet.data.type_label}
          page={pageSizeMm(sheet.data.geometry)}
          strips={type.data.backing_design?.page_size === sheet.data.geometry.page_size ? type.data.backing_design.strips : []}
          initialPrinterId={printerId}
          onClose={onClose}
        />
      ) : (
        <p className="text-ink-2">{t`Loading…`}</p>
      )}
    </ModalDialog>
  );
}
