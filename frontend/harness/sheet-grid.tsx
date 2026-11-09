// Dev-only page for the real-browser checks of SheetGrid and GeometryDiagram (jsdom has no layout engine).
// Served by `vite` for harness/*.spec.ts; never part of the production build (index.html is the only input).
import { I18nProvider } from "@lingui/react";
import { StrictMode, useState } from "react";
import { createRoot } from "react-dom/client";
import "../src/index.css";
import { i18n, initI18n, isLang } from "../src/i18n";
import type { GeometryMm, GridCell } from "../src/features/sheets/cellState";
import { GeometryDiagram } from "../src/features/sheets/GeometryDiagram";
import { SheetGrid, SheetLegend } from "../src/features/sheets/SheetGrid";

const A4 = { page_size: "A4", page_w: 210, page_h: 297 } as const;
const TYPES: Record<string, GeometryMm> = {
  l4731: { ...A4, label_w: 25.4, label_h: 10, cols: 7, rows: 27, pitch_x: 27.9, pitch_y: 10, margin_top: 13.5, margin_left: 8.6, corner_radius: 1.5, shape: "rectangle" },
  l4736: { ...A4, label_w: 45.7, label_h: 21.2, cols: 4, rows: 12, pitch_x: 48.2, pitch_y: 21.2, margin_top: 21.3, margin_left: 9.85, corner_radius: null, shape: "rectangle" },
  round: { ...A4, label_w: 30, label_h: 30, cols: 5, rows: 8, pitch_x: 36, pitch_y: 36, margin_top: 10, margin_left: 15, corner_radius: null, shape: "round" },
  lever: { ...A4, label_w: 190, label_h: 38, cols: 1, rows: 7, pitch_x: 190, pitch_y: 38.5, margin_top: 14, margin_left: 10, corner_radius: 2, shape: "rectangle" },
};
const PURPOSE = "Grocy · " + "flour and other long dry goods ".repeat(5).slice(0, 112); // 120 characters

/** The edge data set: 120 of 189 used with 120-character purposes, one cell of every other state. */
function edgeCells(total: number): GridCell[] {
  const used = total >= 189 ? 120 : Math.floor(total * 0.63);
  const cells: GridCell[] = Array.from({ length: used }, (_, i) => ({ cell: i + 1, state: "used", purpose: PURPOSE, mapped: i % 3 === 0 }));
  const rest: GridCell[] = [
    { cell: used + 1, state: "reserved" },
    { cell: used + 2, state: "unconfirmed" },
    { cell: used + 3, state: "new", isId: true, hwMargin: true },
    { cell: used + 4, state: "new" },
    { cell: used + 5, state: "skipped" },
  ];
  return [...cells, ...rest.filter((c) => c.cell <= total)];
}

// A stand-in for the preview PNG of a printed page: dark text blocks where labels are printed.
const PAGE_IMAGE =
  "data:image/svg+xml," +
  encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 210 297"><rect width="210" height="297" fill="#fff"/>` +
      Array.from({ length: 30 }, (_, i) => `<text x="12" y="${20 + i * 9}" font-size="5" fill="#222">Grocy · flour 1 kg ${i + 1}</text>`).join("") +
      `</svg>`,
  );

function Page() {
  const q = new URLSearchParams(location.search);
  const geometry = TYPES[q.get("type") ?? "l4731"] ?? TYPES.l4731!;
  const mode = (["view", "select", "skip"] as const).find((m) => m === q.get("mode")) ?? "view";
  const [cells, setCells] = useState(() => edgeCells(geometry.cols * geometry.rows));
  const toggle = (n: number) =>
    setCells((all) => {
      const current = all.find((c) => c.cell === n);
      const rest = all.filter((c) => c.cell !== n);
      const state = mode === "skip" ? (current?.state === "skipped" ? "new" : "skipped") : current?.state === "new" ? "free" : "new";
      return [...rest, { cell: n, state }];
    });
  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-4 p-4">
      <h1 className="text-section font-bold">Sheet L4731-0001</h1>
      <SheetLegend counts={{ used: cells.filter((c) => c.state === "used").length }} />
      <SheetGrid geometry={geometry} cells={cells} mode={mode} onToggle={toggle} label="Sheet L4731-0001" overlayPng={q.get("overlay") ? PAGE_IMAGE : undefined} />
      <GeometryDiagram geometry={geometry} />
    </main>
  );
}

const lang = new URLSearchParams(location.search).get("lang");
void initI18n(isLang(lang) ? lang : "en").then(() => {
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <I18nProvider i18n={i18n}>
        <Page />
      </I18nProvider>
    </StrictMode>,
  );
});
