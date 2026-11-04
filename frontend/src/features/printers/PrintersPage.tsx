import { useLingui } from "@lingui/react/macro";
import { PrinterGrid } from "./PrinterGrid";

export function PrintersPage() {
  const { t } = useLingui();
  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-title font-bold">{t`Printers`}</h1>
      <PrinterGrid />
    </div>
  );
}
