// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
// M1 — "Edit details" → Preprinted areas (spec 5.1, 5.4).

import { GEOM, DEMO_ID, DEMO_ZONES, TOP_BAND, badge, btn, field, icon, input, note, select, shell, sheetSvg } from "../lib.mjs";
import { LEGEND, positionControls } from "../parts.mjs";

const g = GEOM.l4736;
const bad = { x: 12, y: 22, w: 30, h: 6 };

const zoneRow = (z, i, kind) => `<div class="zrow">
  <span class="n">${i}</span>
  <span class="row g8 wrap-row"><span class="bold">${z.note}</span>${kind === "preset" ? badge("Preset", "info", "lock") : ""}</span>
  <span class="acts">${kind === "preset" ? "" : `<button class="icon-btn" aria-label="Edit ${z.note}">${icon("pencil", 20)}</button><button class="icon-btn" aria-label="Remove ${z.note}" style="color:var(--bad)">${icon("trash", 20)}</button>`}</span>
  <span class="vals">x <b class="mono">${z.x.toFixed(1)}</b> · y <b class="mono">${z.y.toFixed(1)}</b> · width <b class="mono">${z.w.toFixed(1)}</b> · height <b class="mono">${z.h.toFixed(1)}</b> mm${kind === "preset" ? " · unlink the preset to change it" : ""}</span></div>`;

const diagram = `<div class="panel col g16">
  <div class="row between"><h3 class="section">Sheet front</h3>${badge("Preview of the saved rules", "plain")}</div>
  <div style="max-width:340px;margin:0 auto;width:100%">${sheetSvg({ g, zones: DEMO_ZONES, badZones: [bad], idRect: DEMO_ID, hw: { t: 4.2, b: 4.2, l: 4.2, r: 4.2 }, label: "Sheet front with the preprinted areas hatched, the planned sheet code outlined and the refused area dashed red" })}</div>
  <div class="col g8"><p class="lbl">Top band, enlarged in two halves</p>
    ${sheetSvg({ g, view: [0, 0, 105, 34], zones: DEMO_ZONES, badZones: [bad], idRect: DEMO_ID, bands: TOP_BAND, hw: { t: 4.2, b: 4.2, l: 4.2, r: 4.2 }, extra: `<text class="sv-t" x="27" y="12.6" font-size="3" text-anchor="middle">Logo</text><text class="sv-t" x="74.5" y="12.6" font-size="3" text-anchor="middle">Product description</text><text class="sv-t b" x="27" y="26.2" font-size="3" text-anchor="middle" style="fill:var(--bad)">covers label 1</text>`, label: "Left half of the top band, enlarged" })}
    ${sheetSvg({ g, view: [105, 0, 105, 34], zones: DEMO_ZONES, badZones: [bad], idRect: DEMO_ID, bands: TOP_BAND, hw: { t: 4.2, b: 4.2, l: 4.2, r: 4.2 }, extra: `<text class="sv-t b" x="${DEMO_ID.x + DEMO_ID.w / 2}" y="${DEMO_ID.y + DEMO_ID.h / 2 + 1}" font-size="3" text-anchor="middle">sheet code</text><text class="sv-t" x="174" y="12.6" font-size="3" text-anchor="middle">Size text</text>`, label: "Right half of the top band, enlarged" })}
    <p class="hint">Green: free after the printer's unprintable edge (amber) and the areas. The code takes the free stretch between the product description and the size text.</p></div>
  ${LEGEND}</div>`;

const form = `<div class="col g24">
  <div class="col g4"><div class="crumbs"><a href="#">Sheet archive</a><span>/</span><a href="#">Avery Zweckform L4736REV</a><span>/</span><span>Edit details</span></div>
    <h1 class="title">Edit details</h1>
    <p class="muted">Avery Zweckform L4736REV · <span class="mono">avery-zweckform-l4736rev</span> · saving adds version 2, sheets keep version 1.</p></div>
  ${note("bad", "1 area was not saved", "Area 5 covers label 1 (row 1, column 1). Preprint sits in the margins, so a label there would be printed on top of it. Move the area out of the labels or remove it.")}
  <section class="panel col g16" aria-labelledby="pos-h"><div class="col g4"><h2 class="section" id="pos-h">Sheet code position</h2>
    <p class="muted">Where the margin sheet code is printed. Checked against every page printer on the type page.</p></div>
    ${positionControls()}</section>
  <section class="panel col g16" aria-labelledby="zones-h">
    <div class="col g4"><h2 class="section" id="zones-h">Preprinted areas</h2>
      <p class="muted">Where the vendor printed on the front of the sheet. The hub keeps the sheet code, its QR code and the feed mark out of these areas.</p></div>
    <div class="grid2"><div class="field"><label>Vendor preset</label>${select("Avery Zweckform L4736REV (example)")}
        <p class="hint">Areas of the preset and your own areas are all kept free.</p></div>
      <div class="field"><label>&nbsp;</label><span class="row g8">${btn("Unlink preset and keep a copy", "sm")}</span></div></div>
    <div class="table-wrap">
      ${zoneRow(DEMO_ZONES[0], 1, "preset")}${zoneRow(DEMO_ZONES[1], 2, "preset")}${zoneRow(DEMO_ZONES[2], 3, "preset")}
      ${zoneRow({ x: 10, y: 288.4, w: 190, h: 5, note: "Bottom line" }, 4, "own")}
      <div class="zrow badrow"><span class="n">5</span><span class="bold">Dust cover</span>
        <span class="acts"><button class="icon-btn" aria-label="Edit Dust cover">${icon("pencil", 20)}</button><button class="icon-btn" aria-label="Remove Dust cover" style="color:var(--bad)">${icon("trash", 20)}</button></span>
        <span class="vals">x <b class="mono">12.0</b> · y <b class="mono">22.0</b> · width <b class="mono">30.0</b> · height <b class="mono">6.0</b> mm</span>
        <p class="err msg">${icon("x", 16)}<span>Covers label 1 (R1 C1). <span class="mono small">preprint_zone_overlaps_cell</span></span></p></div>
    </div>
    <div class="row between wrap-row"><p class="small muted">5 of 16 areas</p>${btn("Add area", "", "plus")}</div></section>
  <div class="row g8 wrap-row">${btn("Save details", "primary")}${btn("Cancel")}<span class="small muted">Saving checks the areas against the labels and refuses a bad one.</span></div>
</div>`;

const editor = `<div class="scrim" role="dialog" aria-modal="true" aria-labelledby="ed-h"><div class="dialog">
  <header><h2 id="ed-h">Edit area 5</h2><p class="muted small">From the sheet's top-left corner, in mm.</p></header>
  <div class="body">
    ${field("Note", input("Dust cover"), "")}
    <div class="grid2 keep">${field("x", input("12.0", { unit: "mm" }))}${field("y", input("22.0", { unit: "mm" }))}</div>
    <div class="grid2 keep">${field("Width", input("30.0", { unit: "mm", focus: true, caret: true }))}${field("Height", input("6.0", { unit: "mm" }))}</div>
    ${note("bad", "", "Covers label 1 (R1 C1). Move it above 21.3 mm or shrink it so it stays out of the labels.")}
  </div>
  <footer>${btn("Cancel")}${btn("Save area", "primary")}</footer></div></div>`;

export default {
  file: "m01-preprinted-areas",
  title: "M1 Edit details: preprinted areas",
  views: ["default", "editor"],
  viewSpecs: [{ id: "default" }, { id: "editor", kb: true }],
  modalViews: ["editor"],
  body: () => shell({
    active: "Sheet archive",
    content: `<div class="split-wide wide-side">${form}<div class="col stick">${diagram}</div></div>
      <div data-only="editor">${editor}</div>`,
    notes: [
      "Spec 5.1 and 5.4: the zone list (x, y, w, h in mm plus note), the preset picker, the hatched zones and the planned sheet-code rectangle in the diagram.",
      "Area 5 shows the refusal for a zone over a label (422 <code>preprint_zone_overlaps_cell</code>); the diagram draws it red and dashed.",
      "The zone numbers are invented demo values. The real Avery Zweckform preset waits for the operator's measurement photos (task 10c).",
      "View <code>editor</code> is the zone dialog with the keyboard open: x, y, width and height sit in a two-column grid, Save stays in the sticky footer (spec 12).",
    ],
  }),
};
