// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
// M2 — Type detail → Sheet code section (spec 5.3).

import { GEOM, DEMO_ID, DEMO_ZONES, TOP_BAND, badge, btn, icon, note, select, shell, sheetSvg } from "../lib.mjs";
import { LEGEND, positionControls } from "../parts.mjs";

const g = GEOM.l4736;
const rows = [
  { p: "Office laser", t: "Tray 1 (manual feed)", ok: true, pos: "Top band, 54.0 mm from the right", lvl: "QR + code + type text", lv: "ok", reason: "" },
  { p: "Hallway colour laser", t: "Tray 2", ok: true, pos: "Top band, 54.0 mm from the right", lvl: "QR + code", lv: "info", reason: "The type text does not fit beside the QR here: the free stretch is 3 mm shorter on this printer." },
  { p: "Desk inkjet", t: "Tray 1", ok: false, pos: "—", lvl: "Not printed", lv: "bad", code: "too_small", reason: "The printer cannot print the top 12 mm. The band left is 8.3 mm deep and the code needs 9 mm with a QR." },
  { p: "Archive laser", t: "Tray 1", ok: false, pos: "—", lvl: "Not printed", lv: "bad", code: "overlaps_preprint", reason: "With this tray's correction (+1.4 mm across) the code would touch the size text." },
];
const tr = rows.map((r, i) => `<li class="prow${i === 0 ? " sel" : ""}">
  <div class="row between wrap-row"><span class="bold">${r.p} <span class="muted" style="font-weight:400">· ${r.t}</span></span>
    <span class="row g8 wrap-row">${r.ok ? badge("Fits", "ok", "check") : badge("Does not fit", "bad", "x")}${badge(r.lvl, r.lv === "bad" ? "plain" : r.lv)}</span></div>
  <p class="small">${r.ok ? r.pos : "Not printed in the margin"}</p>
  ${r.reason ? `<p class="small muted">${r.reason}${r.code ? ` <span class="mono faint">${r.code}</span>` : ""}</p>` : ""}</li>`).join("");

const content = `<div class="col g24">
  <div class="col g4"><div class="crumbs"><a href="#">Sheet archive</a><span>/</span><span>Avery Zweckform L4736REV</span></div>
    <div class="row between wrap-row"><h1 class="title">Avery Zweckform L4736REV</h1><span class="row g8 wrap-row">${btn("Edit details", "", "pencil")}${btn("Probe print", "", "qr")}</span></div>
    <div class="tabs" role="tablist"><span class="t">Measurements</span><span class="t on">Sheet code</span><span class="t">Versions</span><span class="t">Sheets <span class="count">12</span></span><span class="t">Log</span></div></div>
  <div class="split-wide wide-side">
  <div class="col g24">
    <section class="col g16" aria-labelledby="sc-h"><div class="col g4"><h2 class="section" id="sc-h">Where the sheet code goes</h2>
      <p class="muted">The sheet code identifies a sheet when you scan it. Choose where the hub prints it.</p></div>
      <div class="panel col g8" style="border-color:var(--accent);box-shadow:inset 0 0 0 1px var(--accent)">
        <span class="row g8"><span class="bold">In the margin</span>${badge("Chosen", "info")}</span><span class="muted">Prints the code in the free band around the labels. No extra pass through the printer.</span></div>
      <div class="row g8 wrap-row small muted"><span>Other choices: Automatic · Back of the liner · A label cell</span></div></section>
    <section class="panel col g16" aria-labelledby="pos-h"><h3 id="pos-h">Position in the margin</h3>${positionControls()}
      <div class="row g8 wrap-row">${btn("Save position", "primary")}<span class="small muted">Edit details also holds the preprinted areas (4 areas, 1 preset).</span></div></section>
    <section class="col g16" aria-labelledby="pp-h"><div class="col g4"><h2 class="section" id="pp-h">On your printers</h2>
      <p class="muted">One row per enabled page printer, with the tray its sheets use. Pick another tray on a row to check it.</p></div>
      <ul class="table-wrap" aria-label="Printers">${tr}</ul>
      ${note("warn", "2 of 4 printers do not print the code in the margin", "On those pages the hub falls back to the setting of this type: the code goes on a cell. Change the band or the printer's correction if you want it in the margin.")}</section>
  </div>
  <div class="col stick"><div class="panel col g16"><h3 class="section">Chosen place</h3>
    <div class="field"><label>Printer</label>${select("Office laser · Tray 1 (manual feed)")}</div>
    <div style="max-width:300px;margin:0 auto;width:100%">${sheetSvg({ g, zones: DEMO_ZONES, idRect: DEMO_ID, hw: { t: 4.2, b: 4.2, l: 4.2, r: 4.2 }, label: "Sheet front: the sheet code in the top band between product description and size text" })}</div>
    ${sheetSvg({ g, view: [95, 0, 110, 30], zones: DEMO_ZONES, idRect: DEMO_ID, bands: TOP_BAND, hw: { t: 4.2, b: 4.2, l: 4.2, r: 4.2 }, extra: `<text class="sv-t b" x="${DEMO_ID.x + DEMO_ID.w / 2}" y="${DEMO_ID.y + DEMO_ID.h / 2 + 1}" font-size="3" text-anchor="middle">sheet code</text><text class="sv-t" x="174" y="12.6" font-size="3" text-anchor="middle">Size text</text><text class="sv-t" x="${DEMO_ID.x + DEMO_ID.w / 2}" y="${DEMO_ID.y + DEMO_ID.h + 4}" font-size="2.6" text-anchor="middle">42 × 12 mm</text>`, label: "Top band enlarged" })}
    <dl class="small" style="display:grid;grid-template-columns:auto 1fr;gap:2px 12px"><dt class="muted">Place</dt><dd class="bold">Top band, 104.2 mm from the left</dd><dt class="muted">Size</dt><dd class="bold">42 × 12 mm</dd><dt class="muted">Content</dt><dd class="bold">QR + code + type text</dd></dl>
    ${LEGEND}</div></div>
  </div></div>`;

export default {
  file: "m02-sheet-code-section",
  title: "M2 Type detail: sheet code",
  body: () => shell({ active: "Sheet archive", content, notes: [
    "Spec 5.3: one row per enabled page printer with its default tray; reason codes (<code>too_small</code>, <code>overlaps_preprint</code>, <code>outside_printable</code>, <code>no_margin_band</code>) are shown in words with the code beside them.",
    "The position controls (band, start from, offset) are the same block as in Edit details (M1). The offset steps by 0.5 mm.",
    "The diagram marks the chosen rectangle; the tray selector re-evaluates one other tray without saving anything.",
  ] }),
};
