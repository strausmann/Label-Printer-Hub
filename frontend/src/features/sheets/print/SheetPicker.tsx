import { useLingui } from "@lingui/react/macro";
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Button, ComboBox, Input, Label, ListBox, ListBoxItem, Popover } from "react-aria-components";
import { apiFetch, ApiError } from "../../../api/client";
import { FIELD } from "../../../shell/SignIn";
import { LABEL, ModalDialog } from "../../settings/controls";
import { SECONDARY_BUTTON } from "../../ui";
import { CameraScanner } from "../../scan/CameraScanner";
import type { ScanHit } from "../../scan/decoder";
import type { SheetRead, SheetSummary } from "../api";
import { sheetKey } from "../keys";
import { parseSheetCode } from "../resolver";
import { fittingFirst, freeOf, judgeSheet, type Target } from "./plan";

const NEW_KEY = "__new__";

export interface SheetPickerProps {
  typeKey: string;
  typeLabel: string;
  /** Sheets of the type that are active and have a free cell. */
  sheets: readonly SheetSummary[];
  /** Labels in the print: decides which sheets "fit". */
  needed: number;
  value: Target | null;
  onChange: (target: Target) => void;
  /** The code a new sheet will probably get; null while it is not known. */
  newCode: string | null;
  /** False for an archived type: it offers no new sheet. */
  allowNew?: boolean;
}

/** Why a scanned sheet cannot take the print; null when it can (it is then selected). */
function useScanNote(typeKey: string, typeLabel: string) {
  const { t } = useLingui();
  const client = useQueryClient();
  return async (hit: ScanHit): Promise<{ note: string | null; code?: string }> => {
    const code = parseSheetCode(hit.text);
    if (!code) return { note: t`That is not a sheet code.` };
    let sheet: SheetRead | null;
    try {
      sheet = await client.fetchQuery({ queryKey: sheetKey(code), queryFn: () => apiFetch<SheetRead>(`/api/v1/sheets/${encodeURIComponent(code)}`), staleTime: 0 });
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) sheet = null;
      else return { note: t`${code} could not be checked. Try again.` };
    }
    const verdict = judgeSheet(sheet, typeKey);
    switch (verdict.kind) {
      case "ok":
        return { note: null, code };
      case "unknown":
        return { note: t`The hub does not know a sheet ${code}.` };
      case "discarded":
        return { note: t`${code} is discarded and cannot take labels any more.` };
      case "full":
        return { note: t`${code} has no free cell left.` };
      case "other_type":
        return { note: t`${code} is not a sheet of this type. This print uses ${typeLabel} sheets.` };
    }
  };
}

/**
 * The combobox of sheets: the ones that hold the whole print first, then the too small ones, and
 * "New sheet" last; typing searches by code. The scan button reads a sheet's printed code with the
 * camera and selects that sheet, or says why it cannot be used.
 */
export function SheetPicker({ typeKey, typeLabel, sheets, needed, value, onChange, newCode, allowNew = true }: SheetPickerProps) {
  const { t } = useLingui();
  const scanNote = useScanNote(typeKey, typeLabel);
  const [scanning, setScanning] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [typed, setTyped] = useState<string | null>(null);

  const ranked = fittingFirst(sheets, needed);
  const newText = newCode ? t`New ${typeLabel} sheet, becomes ${newCode}` : t`New ${typeLabel} sheet`;
  const selectedKey = value === null ? null : value.kind === "new" ? NEW_KEY : value.code;
  const selectedText = value === null ? "" : value.kind === "new" ? newText : value.code;
  const search = (typed ?? "").trim().toLowerCase();
  const shown = ranked.filter(({ sheet }) => search === "" || sheet.code.toLowerCase().includes(search));

  async function onHit(hit: ScanHit) {
    setScanning(false);
    const result = await scanNote(hit);
    setNote(result.note);
    if (result.note === null && result.code) onChange({ kind: "sheet", code: result.code });
  }

  return (
    <div className="flex min-w-0 flex-col gap-2">
      <div className="flex flex-wrap items-end gap-2">
        <ComboBox
          className="flex min-w-0 flex-1 basis-60 flex-col gap-1.5"
          selectedKey={selectedKey}
          inputValue={typed ?? selectedText}
          onInputChange={(text) =>
            // The box shows the chosen sheet's text; only other text is a search.
            setTyped(text === selectedText || text === newText || ranked.some(({ sheet }) => sheet.code === text) ? null : text)
          }
          onSelectionChange={(key) => {
            if (key === null) return;
            setNote(null);
            setTyped(null);
            onChange(key === NEW_KEY ? { kind: "new" } : { kind: "sheet", code: String(key) });
          }}
          onBlur={() => setTyped(null)}
          menuTrigger="focus"
          allowsEmptyCollection
        >
          <Label className={LABEL}>{t`Sheet`}</Label>
          <Input className={`${FIELD} font-mono`} autoCapitalize="characters" autoCorrect="off" spellCheck={false} />
          <Popover className="flex w-(--trigger-width) flex-col rounded-r2 border border-line-strong bg-surface p-1 shadow-lg data-[entering]:animate-[popin_140ms_cubic-bezier(0.23,1,0.32,1)]">
            <ListBox className="max-h-[inherit] overflow-y-auto overscroll-contain outline-none">
              {shown.map(({ sheet, fits }) => {
                const free = freeOf(sheet);
                return (
                  <ListBoxItem
                    key={sheet.code}
                    id={sheet.code}
                    textValue={sheet.code}
                    className="flex min-h-11 cursor-default flex-wrap items-center gap-x-3 rounded-r1 px-3 py-1 text-ink outline-none data-[focused]:bg-sunken data-[selected]:font-bold"
                  >
                    <span className="font-mono">{sheet.code}</span>
                    <span className="text-small tabular-nums text-ink-2">{t`${free} free`}</span>
                    <span className="text-small font-bold">{fits ? t`fits ${needed}` : t`too small`}</span>
                  </ListBoxItem>
                );
              })}
              {allowNew && (
                <ListBoxItem id={NEW_KEY} textValue={newText} className="flex min-h-11 cursor-default items-center rounded-r1 px-3 text-ink outline-none data-[focused]:bg-sunken data-[selected]:font-bold">
                  {`+ ${newText}`}
                </ListBoxItem>
              )}
            </ListBox>
          </Popover>
        </ComboBox>
        <Button className={SECONDARY_BUTTON} onPress={() => setScanning(true)}>
          {t`Scan a sheet code`}
        </Button>
      </div>
      {note && <p role="alert" className="text-small font-bold text-ink [overflow-wrap:anywhere]">{note}</p>}
      <ModalDialog title={t`Scan a sheet code`} isOpen={scanning} onClose={() => setScanning(false)}>
        {scanning && <CameraScanner onHit={(hit) => void onHit(hit)} onClose={() => setScanning(false)} />}
      </ModalDialog>
    </div>
  );
}
