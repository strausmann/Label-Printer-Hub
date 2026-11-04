import { Link } from "@tanstack/react-router";
import { StatusBadge } from "../../shell/StatusBadge";
import type { Printer, PrinterStatus } from "./api";
import { describePrinter, useKindLabel } from "./model";
import { TapeSwatch } from "./TapeSwatch";

/** One printer: name, state (shape + word), loaded tape. The whole card opens the detail page. */
export function PrinterCard({
  printer,
  status,
  printing,
}: {
  printer: Printer;
  status: PrinterStatus | undefined;
  printing: boolean;
}) {
  const kinds = useKindLabel();
  const view = describePrinter(printer, status, printing);
  return (
    <Link
      to="/printers/$printerId"
      params={{ printerId: printer.id }}
      className="press flex h-full flex-col gap-3 rounded-r3 border border-line bg-surface p-4 transition-colors duration-150 hover:bg-sunken focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-link"
    >
      <span className="flex flex-col">
        <span className="text-body font-bold">{printer.name}</span>
        <span className="text-small text-ink-2">{printer.model}</span>
      </span>
      <StatusBadge state={view.badge} label={kinds[view.kind]} />
      {view.detail && <span className="text-small text-ink-2">{view.detail}</span>}
      <span className="mt-auto text-small">
        <TapeSwatch tapeLoaded={status?.tape_loaded} probed={status?.captured_at != null} />
      </span>
    </Link>
  );
}
