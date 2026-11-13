import { useLingui } from "@lingui/react/macro";
import { ApiError } from "../../../api/client";
import { contentTypeDataMismatch, itemIndexOf, trayUnknown } from "../../../api/errorDetail";
import { useSheetErrorText } from "../errors";

/**
 * The words for a failed preview or print. The ones that need the item's name or the printer's
 * trays come first; everything else is the sheet screens' table. `itemName` turns the index of an
 * expanded item (one per copy) back into the name on the label.
 */
export function usePrintDialogErrorText(itemName: (index: number) => string): (error: unknown) => string {
  const { t } = useLingui();
  const sheetText = useSheetErrorText();
  return (error) => {
    if (error instanceof ApiError) {
      if (error.code === "render-timeout") {
        return t`The preview took too long. Try again later.`;
      }
      if (error.code === "render-unavailable") {
        return t`The hub cannot draw a preview right now. Try again later.`;
      }
      if (error.code === "preview_too_large") {
        const pages = Number(error.errorDetail?.pages ?? 0);
        const max = Number(error.errorDetail?.max ?? 10);
        return t`These labels need ${pages} pages, and at most ${max} pages can be previewed at once. Print fewer labels, or print in two rounds.`;
      }
      const mismatch = contentTypeDataMismatch(error);
      if (mismatch) {
        const name = itemName(mismatch.itemIndex);
        const fields = mismatch.missingFields.join(", ");
        return t`${name} cannot be printed with this layout: ${fields} is missing. Choose another layout.`;
      }
      if (error.code?.startsWith("integration_")) {
        const index = itemIndexOf(error);
        const code = error.code;
        if (index !== null) {
          const name = itemName(index);
          return t`${name}: the app behind this item did not answer (${code}). Check Settings › Integrations.`;
        }
        return t`The app behind an item did not answer (${code}). Check Settings › Integrations.`;
      }
      if (error.code === "app-lookup-not-found") {
        return t`An item is no longer in its app, so it cannot be printed. Remove it from the cart and try again.`;
      }
      const trays = trayUnknown(error);
      if (trays) {
        const list = trays.trays.join(", ");
        return trays.trays.length > 0
          ? t`The tray you chose is not available on this printer. It reports: ${list}.`
          : t`The tray you chose is not available: the printer reports no trays.`;
      }
    }
    return sheetText(error, t`The labels could not be put on the sheet.`);
  };
}
