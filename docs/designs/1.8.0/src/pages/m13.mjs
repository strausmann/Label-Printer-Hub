// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
// M13 — Sheet detail → cell panel (spec 8.1).

import { GEOM, badge, btn, icon, note, shell } from "../lib.mjs";
import { qr } from "../paper.mjs";

const g = GEOM.z6121;
const items = [
  ["ASSET-0101", "Laptop dock"], ["ASSET-0102", "Monitor arm"], ["ASSET-0103", "Cable box A"], ["ASSET-0104", "Router spare"], ["ASSET-0105", "Label printer"],
  ["ASSET-0106", "Torx set"], ["ASSET-0107", "Soldering iron"], ["ASSET-0108", "Multimeter"], null, ["ASSET-0110", "Heat gun"],
  ["ASSET-0111", "Tape measure"], ["ASSET-0142", "Torx screwdriver set"], ["ASSET-0143", "Cordless drill"], ["ASSET-0144", "Drill bits"],
];
const kind = (n) => (n <= 14 ? (items[n - 1] ? "used" : "old") : n === 15 ? "hand" : n === 16 ? "code" : n <= 18 ? "reserved" : "free");
const SEL = 12;

const cell = (n) => {
  const k = kind(n);
  const sel = n === SEL;
  const body = k === "used" ? `<span class="row g4 ctext1">${icon("asset", 14)}<b class="mono">${items[n - 1][0]}</b></span><span class="ctext hide-narrow">${items[n - 1][1]}</span>`
    : k === "old" ? `<span class="ctext1 faint">${icon("info", 14)}<span class="hide-narrow"> Not recorded</span></span>`
    : k === "hand" ? `<span class="ctext1 faint">${icon("pencil", 14)}<span class="hide-narrow"> Marked by hand</span></span>`
    : k === "code" ? `<span class="ctext1 bold">${icon("qr", 14)}<span class="hide-narrow"> Sheet code</span></span>`
    : k === "reserved" ? `<span class="ctext1" style="color:var(--reserved-line)">${icon("clock", 14)}<span class="hide-narrow"> Printing…</span></span>` : "";
  return `<li class="cell ${k}${sel ? " sel" : ""}" aria-label="Cell ${n}"><span class="cn">${n}</span>${body}</li>`;
};
const grid = `<ol class="cgrid" aria-label="Sheet cells">${Array.from({ length: 65 }, (_, i) => cell(i + 1)).join("")}</ol>`;

const labelArt = `<svg viewBox="0 0 76.2 42.36" role="img" aria-label="Rendered label, ASSET-0142 Torx screwdriver set" style="width:100%;height:auto;background:#fff;border:1px solid var(--line-strong);border-radius:4px"><svg x="3" y="6" width="30" height="30" viewBox="0 0 30 30">${qr("LYC1:12:7:K1", 15, 15, 30)}</svg>
  <text x="36" y="14" font-size="5.6" font-weight="700" fill="#1B1B1B" font-family="Atkinson Hyperlegible Mono">ASSET-0142</text><text x="36" y="22" font-size="4.2" fill="#1B1B1B" font-family="Atkinson Hyperlegible">Torx screwdriver</text><text x="36" y="27" font-size="4.2" fill="#1B1B1B" font-family="Atkinson Hyperlegible">set</text><text x="36" y="36" font-size="3.4" fill="#555" font-family="Atkinson Hyperlegible">Workshop · Shelf 2</text></svg>`;

const panel = (v) => v === "old" ? `<aside class="panel col g16" aria-label="Cell 9"><div class="row between"><h2 class="section">Cell 9</h2><button class="icon-btn" aria-label="Close">${icon("close", 22)}</button></div>
  ${badge("Not recorded", "plain", "info")}
  <p>This cell was printed before 1.8.0. The hub did not keep what was printed on it, so there is nothing to show or print again.</p>
  <dl class="small dl2"><dt class="muted">State</dt><dd class="bold">Used</dd><dt class="muted">Printed</dt><dd>2026-11-02 (job #4107)</dd></dl>
  <div class="row g8 wrap-row">${btn("Print again", "primary disabled")}</div></aside>`
  : `<aside class="panel col g16" aria-label="Cell 12"><div class="row between"><h2 class="section">Cell 12</h2><button class="icon-btn" aria-label="Close">${icon("close", 22)}</button></div>
  <div class="col g8">${labelArt}<p class="small muted">Rendered now from what was stored when the cell was reserved. No image is kept.</p></div>
  <dl class="small dl2"><dt class="muted">Item</dt><dd class="bold">Snipe-IT · asset 142</dd><dt class="muted">Purpose</dt><dd>Item label</dd><dt class="muted">Printed</dt><dd>2026-11-19 10:42 · <a href="#">job #4312</a></dd><dt class="muted">Content</dt><dd>Title, ID, 1 line, QR</dd></dl>
  <div class="row g8 wrap-row">${btn("Print again", "primary", "printers")}${btn("Open in Snipe-IT", "", "external")}</div>
  <p class="small muted">\"Open in\" appears when a public web address is set for the integration (M11).</p></aside>`;

export default {
  file: "m13-cell-panel",
  title: "M13 Sheet detail: cell panel",
  views: ["default", "old"],
  viewSpecs: [{ id: "default" }, { id: "old" }],
  css: `.cgrid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:4px;margin:0;padding:0;list-style:none}.cell{position:relative;display:flex;flex-direction:column;justify-content:center;gap:2px;aspect-ratio:38.1/21.18;padding:4px 6px;border:1px solid var(--line-strong);border-radius:6px;background:var(--surface);overflow:hidden;font-size:13px;min-width:0}
  .cn{position:absolute;top:2px;left:4px;font-size:11px;color:var(--cell-number)}.cell .ctext1{display:flex;align-items:center;gap:4px;font-size:12px;white-space:nowrap;overflow:hidden;margin-top:8px}.cell .ctext{font-size:12px;color:var(--ink-2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .cell.used{background:var(--sunken)}.cell.old,.cell.hand{background:var(--sunken)}.cell.code{background:var(--info-soft);border-color:var(--link)}.cell.reserved{background:repeating-linear-gradient(-45deg,var(--accent-soft) 0 4px,transparent 4px 8px);border-color:var(--accent)}.cell.free{border-style:dashed;background:transparent}
  .cell.sel{border:2px solid var(--accent);box-shadow:0 0 0 2px var(--accent-soft)}html[data-view="old"] .cell.sel{border:1px solid var(--line-strong);box-shadow:none}html[data-view="old"] .cell:nth-child(9){border:2px solid var(--accent);box-shadow:0 0 0 2px var(--accent-soft)}
  .dl2{display:grid;grid-template-columns:auto 1fr;gap:4px 16px;margin:0}.dl2 dd{margin:0}.row.g4{gap:4px}
  @media(max-width:639px){.cell .ctext1 b{display:none}.cell{padding:2px;align-items:center}.cell .ctext1{margin-top:6px}}`,
  body: () => shell({
    active: "Sheets",
    content: `<div class="col g24"><div class="col g4"><div class="crumbs"><a href="#">Sheets</a><span>/</span><span>A6121-0007</span></div>
      <div class="row between wrap-row g8"><h1 class="title mono">A6121-0007</h1><span class="row g8 wrap-row">${btn("Print on this sheet", "primary", "printers")}${btn("Mark cells by hand")}</span></div>
      <p class="muted"><a href="#">Avery Zweckform 6121 · v1</a> · 14 used, 2 reserved, 1 sheet code, 48 free</p></div>
      <div class="split-wide wide-side" style="--side:24rem"><div class="col g16"><ul class="row g16 wrap-row small muted" aria-label="Legend"><li>${badge("Used: item and first line", "plain")}</li><li>${badge("Reserved", "warn", "clock")}</li><li>${badge("Free", "plain")}</li></ul>${grid}</div>
      <div class="col stick"><div data-not="old">${panel("used")}</div><div data-only="old">${panel("old")}</div></div></div></div>`,
    notes: [
      "Spec 8.1 (#248): the grid shows text only: the integration icon, the reference and the first line. Nothing is rendered or fetched when the page loads (asserted by an e2e test); a click opens the panel with the label rendered on demand.",
      "Panel actions: \"Print again\" (opens the print dialog with the stored item) and \"Open in Snipe-IT\" when the integration has a public web address (#247). The QR in the rendered label is a stand-in for the item's real code.",
      "Cells printed before 1.8.0 say \"Not recorded\" (view <code>old</code>), hand-marked cells \"Marked by hand\", the ID cell \"Sheet code\". On a phone the cells show icon and number only and the panel sits below the grid.",
    ],
  }),
};
