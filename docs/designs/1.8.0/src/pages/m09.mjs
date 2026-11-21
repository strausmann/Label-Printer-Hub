// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
// M9 — Type detail → Probe print (spec 7.3), with the measurement sheet of #246.

import { badge, btn, checkbox, field, icon, mockNotes, note, select } from "../lib.mjs";
import { probePage } from "../paper.mjs";

const dialog = (bad) => `<div class="panel col g16" style="background:var(--surface)"><div class="col g4"><h2 class="section">Probe print on plain paper</h2>
  <p class="muted small">Prints the outline of every label so you can hold the page against a real sheet. No sheet is used, no cell is reserved.</p></div>
  ${field("Printer", select(bad ? "Archive laser" : "Office laser"))}
  ${field("Tray", select("Tray 1 (manual feed)"), "The current correction of this tray is applied: dx +0.41 mm, dy −0.66 mm.")}
  ${checkbox("Measurement sheet: add a millimetre grid, no correction", bad ? false : false)}
  ${bad ? note("bad", "Archive laser is offline", "Its status was read at 14:49 and the printer did not answer. Switch it on, or choose another printer. (409 <code>printer-offline</code>)") : note("info", "", "It goes through the print queue: you can see it under Jobs and retry it.")}
  <div class="row g8 wrap-row">${btn("Print probe page", bad ? "primary disabled" : "primary", "qr")}${btn("Download PDF")}</div></div>`;

const fig = (svg, cap) => `<figure><div class="paper">${svg}</div><figcaption class="paper-cap">${cap}</figcaption></figure>`;

export default {
  file: "m09-probe-print",
  title: "M9 Type detail: probe print",
  paper: true,
  css: `.pg{max-width:1216px;margin:0 auto;display:flex;flex-direction:column;gap:32px}.top{display:grid;grid-template-columns:minmax(0,1.1fr) minmax(0,1fr) minmax(0,1fr);gap:24px;align-items:start}.two{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:32px;align-items:start}figure{margin:0}.paper-cap{max-width:56ch;margin-inline:auto}.pg .mock-notes{margin:0;background:var(--surface)}
  @media (max-width:900px){.top,.two{grid-template-columns:minmax(0,1fr)}}`,
  body: () => `<div class="desk"><div class="pg">
    <section class="panel col g16" style="background:var(--surface)"><div class="col g4"><div class="crumbs"><a href="#">Sheet archive</a><span>/</span><span>Avery Zweckform L4736REV</span></div>
      <div class="row between wrap-row"><h1 class="title">Avery Zweckform L4736REV</h1><span class="row g8 wrap-row">${btn("Edit details", "", "pencil")}${btn("Probe print on plain paper", "", "qr")}${btn("Measurement sheet", "", "qr")}</span></div></div></section>
    <section class="top">${dialog(false)}${dialog(true)}<div class="col g16">${note("info", "Why a probe page", "Hold it against a real sheet to see whether the labels, the preprinted areas and the planned sheet-code place line up before you print on a sheet.")}${note("warn", "Held while the device is swapped", "If the hub sees a different device behind this printer, probe pages wait like calibration pages: the stored correction would be wrong for it.")}</div></section>
    <section class="two">${fig(probePage(), "Probe page: every label outlined with its number and R/C, the hatched preprinted areas, the planned sheet-code rectangle, run number and time. The current correction is applied.")}
      ${fig(probePage({ grid: true }), "Measurement sheet: the same page plus a millimetre grid from the top-left corner, drawn without correction. Print it on a real L4736REV or L4731REV and photograph it to read the vendor's preprint.")}</section>
    ${mockNotes([
      "Spec 7.3: the action, the printer and tray choice, the refusals (offline printer shown), and the two printed pages. Spec 5.5: the measurement sheet is the grid option of the same job.",
      "Preprint zones and the sheet-code rectangle are example values, not measured. The measurement sheet draws no zones: it exists to find them.",
      "Page grid strokes are drawn a little heavier than the real 0.05 mm so they survive the screenshot; open the A4 PNG for the full-size view. These two pages are paper: the screenshot is light only.",
    ])}</div></div>`,
};
