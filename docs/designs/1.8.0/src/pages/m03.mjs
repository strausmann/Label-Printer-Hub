// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
// M3 — Calibration and check page (paper): three check passes on one Avery Zweckform 6121 sheet (spec 7.2).

import { GEOM, mockNotes } from "../lib.mjs";
import { INK, PASSES, RUN, checkPage, cornerMarks, crossingXY, miniScale, qr, zoom } from "../paper.mjs";
import { cellRect } from "../lib.mjs";

const g = GEOM.z6121;
const COL = { 1: "#2F4E8F", 2: "#B5651B", 3: "#2E7A4E" };

// the same sheet after three passes: labels grey, every pass in its own colour (the paper itself is black)
function composite() {
  let s = `<svg viewBox="0 0 210 297" role="img" aria-label="One sheet after three check passes"><rect width="210" height="297" fill="#fff"/>`;
  for (let n = 1; n <= g.cols * g.rows; n++) { const r = cellRect(g, n); s += `<rect x="${r.x}" y="${r.y}" width="${r.w}" height="${r.h}" fill="none" stroke="#BDBDBD" stroke-width="0.15"/>`; }
  for (const k of [1, 2, 3]) for (const [c, r] of PASSES[k]) { const p = crossingXY(g, c, r); s += miniScale(p.x, p.y, { label: `K${k}`, color: COL[k], lw: 0.22, ls: 4 }); s += `<circle cx="${p.x}" cy="${p.y}" r="5" fill="none" stroke="${COL[k]}" stroke-width="0.25" stroke-dasharray="1 1"/>`; }
  s += `<text x="105" y="150" font-size="7" text-anchor="middle" fill="#8A8A8A">same sheet, passes 1 to 3</text>`;
  return s + "</svg>";
}

const fig = (svg, cap, cls = "") => `<figure class="${cls}"><div class="paper">${svg}</div><figcaption class="paper-cap">${cap}</figcaption></figure>`;

const stripTop = `<svg viewBox="0 0 210 12" role="img" aria-label="The two-line run block in the top margin"><rect width="210" height="12" fill="#fff"/><use href="#pass-2"/></svg>`;
const stripBottom = `<svg viewBox="0 285 210 12" role="img" aria-label="The two-line run block in the bottom margin"><rect y="285" width="210" height="12" fill="#fff"/><use href="#pass-2"/></svg>`;

const body = () => `<div class="desk"><div class="pg">
  <header class="pg-head"><h1 class="title" >Check pages: three passes on one Avery Zweckform 6121 sheet</h1>
    <p class="muted">Printed black on white at 100 %. A check page prints only the crosses of one pass and no gap lines or edge rulers; the next pass lands on crossings that never touch the earlier ones, so one sheet serves three prints.</p></header>
  <section class="row3">
    ${fig(checkPage(g, 1), `Pass 1 of 3 · run #${RUN[1]} · four outer corners and the centre (K1)`)}
    ${fig(checkPage(g, 2), `Pass 2 of 3 · run #${RUN[2]} · inner corners (K2)`)}
    ${fig(checkPage(g, 3), `Pass 3 of 3 · run #${RUN[3]} · what is left (K3, three crossings)`)}
  </section>
  <section class="row3 r2">
    <figure class="span2"><div class="paper">${zoom(1, [0, 0, 72, 46], "Top-left corner of pass 1, enlarged")}</div>
      <figcaption class="paper-cap">Top-left corner of pass 1, enlarged: page code in the 15 mm corner square, two-line run block, outer corner marks (1.8 mm legs), the K1 cross with its mini scale (±2 mm, a tick every 0.5 mm), a cell number and an 8 mm cell code.</figcaption></figure>
    ${fig(composite(), "The three passes on one physical sheet (colours only tell the passes apart here)")}
  </section>
  <section class="row3 r3">
    ${fig(zoom(2, [34, 47, 28, 36], "Two crossings of pass 2, enlarged"), "Pass 2, two crossings: the upper one is not in this pass, so its four corner marks (0.9 mm legs) stay; the lower one is K2 and carries the scale, so the marks next to it are left out")}
    <figure><div class="paper pad"><svg viewBox="0 0 60 60" role="img" aria-label="Page code, longest payload"><rect width="60" height="60" fill="#fff"/>${qr("LYC1:999999:0:AAAAAAAAAA:1000000:-1000:-1000:-50000:-50000:-2000000:K99:PX100000:PY100000:MT100000:ML100000", 30, 30, 56)}</svg></div>
      <figcaption class="paper-cap">The longest page code (107 characters) is a version 5-M symbol: 15 mm square, module 0.333 mm</figcaption></figure>
    <figure><div class="paper pad"><svg viewBox="0 0 60 60" role="img" aria-label="Cell code, longest payload"><rect width="60" height="60" fill="#fff"/>${qr("LYC1:999999:400:K99", 30, 30, 56)}</svg></div>
      <figcaption class="paper-cap">The longest cell code (19 characters) is a version 1-M symbol: 8 mm box, module 0.276 mm. Cells carry only <code>LYC1:&lt;run&gt;:&lt;cell&gt;[:K&lt;pass&gt;]</code></figcaption></figure>
  </section>
  <section class="col g16">
    <figure><div class="paper">${stripTop}</div><figcaption class="paper-cap">Top margin run block of pass 2: date, time, run number, pass, printer, tray, sheet type and version, the correction values and any geometry that differs from the shipped one. Nothing runs across the grid.</figcaption></figure>
    <figure><div class="paper">${stripBottom}</div><figcaption class="paper-cap">Bottom margin: the sheet geometry and how to print. Printer name, type key and tray shorten first when a line is too long; run number, date, time, version and correction values never shorten.</figcaption></figure>
  </section>
  ${mockNotes([
    "Spec 7.2 and the comments of #240: margins only, an 8 mm QR and the number in every cell, inner 0.9 mm and outer 1.8 mm corner marks, page codes in the four 15 mm corner squares, check passes K1 to K3 on one 6121 sheet (maintainer, 2026-11-15).",
    "All codes are real: <code>gen_qr.py</code> encodes the <code>LYC1</code> payloads of section 7.2 in alphanumeric mode (page 5-M, cell 1-M). No payload contains <code>@</code>, <code>://</code>, <code>mailto:</code>, <code>tel:</code>, <code>sms:</code>, <code>WIFI:</code>, <code>geo:</code> or <code>BEGIN:</code> (checked when the codes are generated).",
    "Strokes are drawn 0.13 mm instead of 0.1 mm so they survive the screenshot; the pass pattern beyond pass 1 is my call (section 17 leaves it to the builder): passes never share or touch a crossing, diagonals included, and the build fails if they do.",
    "Demo values: run numbers 12 to 14, printer &quot;Office laser&quot;, correction dx +0.41 mm, dy −0.66 mm.",
  ])}
</div></div>`;

export default {
  file: "m03-check-pages",
  title: "M3 Check pages, three passes on a 6121",
  paper: true,
  css: `.pg{max-width:1216px;margin:0 auto;display:flex;flex-direction:column;gap:32px}.row3{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:24px;align-items:start}.span2{grid-column:span 2}
  figure{margin:0}.paper.pad{padding:24px}.pg .mock-notes{margin:0;background:var(--surface);color:var(--ink-2)}.paper-cap{max-width:60ch;margin-inline:auto}
  @media (max-width:900px){.row3{grid-template-columns:minmax(0,1fr)}.span2{grid-column:auto}}`,
  body,
};
