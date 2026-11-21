// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
// M4 — Archive → Catalog tab (spec 6.1.7).

import { GEOM, badge, btn, checkbox, field, icon, input, note, select, shell, sheetSvg } from "../lib.mjs";
import { archiveHead, thumb } from "../parts.mjs";

const entries = [
  { g: GEOM.z6121, desc: "Universal labels", state: "installed", ver: "Verified 2026-11-15", ev: "Checked on real sheets: laser printer, tray 1, within ±0.3 mm." },
  { g: GEOM.l4731, desc: "Mini labels, removable", state: "update", ver: "Verified 2026-11-15", ev: "Checked on real sheets with a check print and correction.", rev: 3 },
  { g: GEOM.l4736, desc: "Mini labels, removable", state: "add", ver: null, open: true },
  { g: GEOM.z3490, desc: "Universal labels, square cut", state: "add", ver: "Verified 2026-11-15", ev: "Edge to edge: the sheet code goes on the back side." },
];
const dims = (g) => `${g.cols} × ${g.rows} · ${g.lw} × ${g.lh} mm · A4`;

const stateBtn = (e) =>
  e.state === "installed" ? `<span class="row g8 muted bold">${icon("check", 18)}Installed</span>`
  : e.state === "update" ? `<span class="row g8 wrap-row">${badge("Update: catalog version 3", "info", "history")}${btn("Update", "sm")}</span>`
  : btn("Add", "primary sm", "plus");
const verified = (e) => e.ver ? badge(e.ver, "ok", "check") : badge("Not yet validated", "warn", "warn");

const card = (e) => `<li class="item-card${e.open ? " on" : ""}" style="gap:12px">
  <div class="row g16 top">${thumb(e.g)}<div class="col g4 grow"><div class="row between wrap-row g8"><span class="bold">${e.g.name}</span><span class="only-wide">${stateBtn(e)}</span></div>
    <span class="small muted">${e.desc} · ${dims(e.g)}</span><span class="mono small muted wrap">${e.g.key}</span>
    <span class="row g8 wrap-row mt8">${verified(e)}</span>${e.ev ? `<span class="small muted">${e.ev}</span>` : ""}<span class="only-narrow mt8">${stateBtn(e)}</span></div></div>
  ${e.open ? `<div class="grid2" style="padding-top:12px;border-top:1px solid var(--line)"><div style="max-width:210px;width:100%">${sheetSvg({ g: e.g, view: [0, 0, 210, 140], label: "Top of the sheet" })}</div>
    <dl class="small" style="display:grid;grid-template-columns:auto 1fr;gap:2px 12px;align-content:start"><dt class="muted">Labels</dt><dd class="bold">${e.g.cols} × ${e.g.rows}, ${e.g.lw} × ${e.g.lh} mm</dd><dt class="muted">Pitch</dt><dd class="bold">${e.g.px} × ${e.g.py} mm</dd><dt class="muted">Top / left</dt><dd class="bold">${e.g.mt} / ${e.g.ml} mm</dd><dt class="muted">Corner radius</dt><dd class="bold">unknown</dd><dt class="muted">Source</dt><dd>Labelplanet LP48/45 (vendor page not reachable)</dd><dt class="muted">Evidence</dt><dd>Values from one third-party source. Measure before relying on them.</dd></dl></div>` : ""}</li>`;

const filters = `<div class="panel col g16"><div class="field"><label>Search</label><div class="input is-focus">${icon("search", 18)}<span class="grow">zweckform<i class="caret"></i></span></div><p class="hint">Vendor, product code or size.</p></div>
  <div class="grid2"><div class="field"><label>Page</label>${select("A4")}</div><div class="field"><label>Vendor</label>${select("All vendors (3)")}</div></div>
  ${checkbox("Verified only", true)}<p class="small muted" style="margin-top:-8px">Hides entries nobody has checked on a real sheet.</p></div>`;

const list = `<div class="col g16 grow"><p class="small muted" aria-live="polite">4 of 39 entries</p><ul class="col g8" aria-label="Catalog">${entries.map(card).join("")}</ul></div>`;

const empty = `<div class="panel col g16" style="align-items:flex-start;max-width:640px"><h2 class="section">No sheet types yet</h2>
  <p class="muted">A new hub starts with no sheet types. Add the ones you use from the catalog; each takes one click. You can also import a type from a file.</p>
  <div class="row g8 wrap-row">${btn("Open the catalog", "primary")}${btn("Import type")}</div>
  ${note("info", "", "Existing installations keep every type they have. The catalog only adds entries and offers updates; it never changes an installed type by itself.")}</div>`;

export default {
  file: "m04-catalog-tab",
  title: "M4 Archive: catalog tab",
  views: ["default", "empty", "search"],
  viewSpecs: [{ id: "default" }, { id: "empty" }, { id: "search", kb: true }],
  modalViews: ["search"],
  css: `html[data-view="search"] .tabbar{display:none}.kbfit{max-height:calc(var(--vvh,100dvh) - 270px);overflow:auto;overscroll-behavior:contain}`,
  body: () => shell({
    active: "Sheet archive",
    content: `<div class="col g24"><div data-not="empty search">${archiveHead("catalog")}</div><div data-only="search">${archiveHead("catalog", { compact: true })}</div><div data-only="empty">${archiveHead("installed", { counts: [0, 39] })}</div>
      <div data-not="empty search" class="split">${filters}${list}</div>
      <div data-only="empty">${empty}</div>
      <div data-only="search" class="col g16"><div class="field"><div class="input is-focus">${icon("search", 18)}<span class="grow">zwe<i class="caret"></i></span></div></div>
        <div class="kbfit"><ul class="col g8">${entries.slice(0, 4).map(card).join("")}</ul></div></div></div>`,
    notes: [
      "Spec 6.1.7: search, \"Verified only\", a state badge per entry (verified with date and evidence, or \"not yet validated\"), the grid preview, and Add / Installed / Update. The open entry shows its geometry and where the values came from.",
      "An unedited installed type with a newer catalog revision shows \"Update\"; an edited one would show \"The catalog has a newer version\" without the button (spec 6.1.3).",
      "View <code>empty</code> is the Installed tab of a fresh installation; view <code>search</code> is the catalog with the keyboard open: the result list is limited to the visible height and scrolls inside.",
    ],
  }),
};
