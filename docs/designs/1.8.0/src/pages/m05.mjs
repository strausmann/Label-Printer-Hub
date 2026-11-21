// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
// M5 — Archive → Installed list and type detail (spec 6.1.3, 6.1.5, 6.1.6).

import { GEOM, badge, btn, checkbox, field, icon, input, note, select, shell } from "../lib.mjs";
import { archiveHead, thumb } from "../parts.mjs";

const types = [
  { g: GEOM.l4731, free: "2 sheets with free cells · 301 free labels", st: "in", last: "2026-11-20", total: 5, on: true },
  { g: GEOM.z6121, free: "1 sheet with free cells · 38 free labels", st: "in", last: "2026-11-18", total: 9 },
  { g: GEOM.z3490, free: "No sheet with free cells", st: "before", last: "2026-09-02", total: 3 },
  { g: GEOM.l4736, free: "Never used", st: "unused", last: "—", total: 0 },
];
const stBadge = (s) => (s === "in" ? badge("In use", "ok", "check") : s === "before" ? badge("Used before", "info", "history") : badge("Unused", "plain"));

const item = (t) => `<li class="item-card${t.on ? " on" : ""}"><div class="row g16 top">${thumb(t.g, 40)}<div class="col g4 grow">
  <span class="bold wrap">${t.g.name}</span><span class="mono small muted wrap">${t.g.key}</span>
  <span class="row g8 wrap-row">${stBadge(t.st)}<span class="small muted">${t.total} sheets · last used ${t.last}</span></span><span class="small muted">${t.free}</span></div></div></li>`;

const diff = `<div class="panel col g16" style="border-color:var(--link)"><div class="row between wrap-row"><h3 class="section">Update available</h3>${badge("Catalog version 3", "info", "history")}</div>
  <p class="muted">You installed catalog version 2 and have not edited this type. Version 3 changes two measurements. Sheets you already made keep the version they were created with.</p>
  <div class="table-wrap"><table class="tbl"><thead><tr><th>Measurement</th><th class="num">Installed (v2)</th><th class="num">Catalog (v3)</th></tr></thead><tbody>
  <tr><td>Top margin</td><td class="num mono">12.54 mm</td><td class="num mono bold">12.48 mm</td></tr>
  <tr><td>Corner radius</td><td class="num mono">1.5 mm</td><td class="num mono bold">1.6 mm</td></tr></tbody></table></div>
  <div class="row g8 wrap-row">${btn("Update to catalog version 3", "primary")}${btn("Show in the catalog")}</div>
  <p class="small muted">A type you changed yourself shows \"The catalog has a newer version\" without this button. Export it, compare, or delete it and add it again.</p></div>`;

const sheetsList = `<section class="col g12 g16" aria-labelledby="sh-h"><div class="row between wrap-row"><h3 class="section" id="sh-h">Its sheets</h3>${btn("Show in the sheets list", "sm", "external")}</div>
  <ul class="table-wrap">
   ${[["L4731-0007", "In use", "ok", "112 of 189 used · 77 free", "2026-11-20"], ["L4731-0006", "In use", "ok", "40 of 189 used · 149 free", "2026-11-12"], ["L4731-0003", "Used up", "info", "189 of 189 used · 0 free", "2026-10-03"]]
     .map(([c, s, k, u, d]) => `<li class="prow"><div class="row between wrap-row"><a class="mono bold" href="#">${c}</a><span class="row g8">${badge(s, k)}<span class="small muted">last use ${d}</span></span></div><span class="small muted">${u}</span></li>`).join("")}
  </ul>
  <div class="row g8">${checkbox("Show discarded (2)")}</div></section>`;

const detail = `<div class="col g24"><div class="col g8"><div class="row between wrap-row"><h2 class="title">Avery Zweckform L4731REV</h2><span class="row g8 wrap-row">${btn("Edit details", "sm", "pencil")}${btn("Delete type", "sm danger disabled", "trash")}</span></div>
    <span class="mono muted wrap">avery-zweckform-l4731rev</span>
    <p class="small muted">Delete is only possible while no sheet uses the type. This type has 5 sheets: archive it instead, or discard its sheets first.</p></div>
  <div class="grid3"><div class="tile"><span class="n">2</span><span class="l">Sheets with free cells</span></div><div class="tile"><span class="n">301</span><span class="l">Free labels</span></div><div class="tile"><span class="n">5</span><span class="l">Sheets in all, last used 2026-11-20</span></div></div>
  ${diff}${sheetsList}</div>`;

const dlg = `<div class="scrim" role="dialog" aria-modal="true" aria-labelledby="rm-h"><div class="dialog">
  <header><h2 id="rm-h">Remove unused types</h2><p class="muted small">These 3 types have no sheets. Nothing is selected: tick the ones to remove.</p></header>
  <div class="body">${field("Filter", `<div class="input is-focus">${icon("search", 18)}<span class="grow faint"><i class="caret"></i>Filter by name</span></div>`)}
    <ul class="col g8">${[["Avery Zweckform L4736REV", "never used · A4 · 4 × 12"], ["Herma 4200 (imported)", "never used · A4 · 3 × 7"], ["Shelf labels (custom)", "never used · A4 · 2 × 6"]]
      .map(([n, s], i) => `<li class="item-card" >${checkbox(`<span class="bold">${n}</span><br><span class="small muted">${s}</span>`)}</li>`).join("")}</ul>
    ${note("info", "", "Sheet codes are never issued twice: the counter of a prefix stays, so a type you add back continues its numbering. A linked backing design is kept.")}
  </div>
  <footer>${btn("Cancel")}${btn("Remove 0 types", "danger disabled", "trash")}</footer></div></div>`;

export default {
  file: "m05-installed-types",
  title: "M5 Archive: installed types",
  views: ["default", "remove"],
  viewSpecs: [{ id: "default" }, { id: "remove", kb: true }],
  modalViews: ["remove"],
  body: () => shell({
    active: "Sheet archive",
    content: `<div class="col g24"><div class="row between wrap-row"><h1 class="title">Sheet archive</h1><div class="row g8 wrap-row">${btn("Remove unused types", "", "trash")}${btn("New type", "primary")}${btn("Import type")}</div></div>
      <div class="tabs"><span class="t on">Installed <span class="count">6</span></span><span class="t">Catalog <span class="count">39</span></span></div>
      <div class="split"><div class="col g16"><div class="panel col g16">
         <div class="grid2"><div class="field"><label>State</label>${select("All")}</div><div class="field"><label>Sort by</label>${select("Usage")}</div></div>
         <div class="grid2"><div class="field"><label>Vendor</label>${select("All (3)")}</div><div class="field"><label>Not used since</label>${input("2026-06-01")}</div></div></div>
         <ul class="col g8" aria-label="Sheet types">${types.map(item).join("")}</ul></div>
       ${detail}</div></div><div data-only="remove">${dlg}</div>`,
    notes: [
      "Spec 6.1.5 and 6.1.6: usage per type (sheets with free cells, free labels, sheets in all, last used, state badge), sorting and the \"not used since\" filter, the type's own sheet list with the discarded toggle, and the catalog-update diff (old to new).",
      "Delete stays disabled while the type has sheets; the text says what to do instead (409 <code>has_sheets</code>).",
      "View <code>remove</code>: \"Remove unused types\" lists exactly the types in state unused with none preselected; filter field and sticky footer work with the keyboard open.",
    ],
  }),
};
