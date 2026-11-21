// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
// M12 — Type detail → Log (spec 7.6).

import { badge, btn, field, icon, input, note, select, shell } from "../lib.mjs";

const V = { fits: badge("Fits", "ok", "check"), geo: badge("Sheet geometry", "warn", "warn"), feed: badge("Feed variance", "info"), printer: badge("Printer", "plain"), none: badge("No verdict", "plain") };
const readings = `<div class="table-wrap"><table class="tbl"><thead><tr><th>Crossing</th><th class="num">Across</th><th class="num">Down</th></tr></thead><tbody>
  <tr><td class="mono bold">S1 · Z1</td><td class="num mono">+0.20 mm</td><td class="num mono">−0.30 mm</td></tr><tr><td class="mono bold">S4 · Z1</td><td class="num mono">+0.60 mm</td><td class="num mono">−0.30 mm</td></tr><tr><td class="mono bold">S4 · Z6</td><td class="num mono">+0.80 mm</td><td class="num mono">0.00 mm</td></tr></tbody></table></div>`;

const entry = (e) => `<li class="entry2"><div class="row between wrap-row g8"><span class="row g8 wrap-row"><span class="bold">${e.title}</span>${e.verdict ?? ""}</span><span class="small muted">${e.when} · ${e.who}</span></div>
  ${e.where ? `<p class="small muted">${e.where}</p>` : ""}${e.body ? `<p>${e.body}</p>` : ""}${e.readings ? `<details open><summary class="small bold">Readings (3 crossings)</summary>${readings}</details>` : ""}${e.corr ? `<p class="small muted">Correction in effect: <a href="#">history entry 3</a> (dx +0.38, dy −0.62 mm)</p>` : ""}</li>`;

const entries = [
  { title: "Check print", verdict: V.geo, when: "2026-11-20 18:40", who: "admin", where: "Office laser · Tray 1 (manual feed) · print #13 · pass 2", body: "Across grows evenly from column 1 to 4 (+0.20 to +0.80 mm) with the correction from the 6121 applied: that is the pitch, not the printer.", readings: true, corr: true },
  { title: "New version 2", when: "2026-11-20 18:55", who: "admin", body: "Pitch across 48.20 → 47.55 mm. Applied from the geometry suggestion of print #13." },
  { title: "Check print", verdict: V.fits, when: "2026-11-20 19:10", who: "admin", where: "Office laser · Tray 1 (manual feed) · print #14 · version 2", body: "Within ±0.2 mm everywhere." },
  { title: "Marked as verified", when: "2026-11-20 19:12", who: "admin", body: "Checked on real sheets, laser printer, tray 1." },
  { title: "Note", verdict: V.feed, when: "2026-11-18 09:02", who: "api key “n8n”", where: "Hallway colour laser · Tray 2", body: "Sheets feed 0.3 mm differently between the first and the last label. Looks like the tray, not the sheet." },
];

const list = `<div class="col g16"><div class="row between wrap-row g8"><div class="grid2 keep" style="flex:1;max-width:520px">${field("Printer", select("All printers"))}${field("Kind", select("All"))}</div>${btn("Add a note", "", "plus")}</div>
  ${note("info", "Internal only", "This log names your printers and trays. It is never part of an export, of the catalog or of a pre-filled feedback issue. Other tools read it through the API: GET /api/v1/sheet-types/{key}/log.")}
  <ul class="table-wrap" aria-label="Log">${entries.map(entry).join("")}</ul><p class="small muted">5 of 5 entries. The newest 500 per type are kept.</p></div>`;

const dlg = `<div class="scrim" role="dialog" aria-modal="true" aria-labelledby="lg-h"><div class="dialog">
  <header><h2 id="lg-h">Add a note</h2><p class="muted small">Avery Zweckform L4736REV · saved with your name.</p></header>
  <div class="body"><div class="grid2 keep">${field("Printer", select("Office laser"))}${field("Tray", select("Tray 1"))}</div>
    <div class="field"><label>Verdict</label><div style="position:relative"><div class="listbox" aria-label="Verdict (the list scrolls)" style="position:absolute;left:0;right:0;bottom:calc(100% + 4px);z-index:2">
      ${["Feed variance", "Printer"].map((o, i) => `<div class="o${i === 0 ? " sel" : ""}"><span>${o}</span>${i === 0 ? icon("check", 18) : ""}</div>`).join("")}</div>${select("Feed variance", { focus: true, up: true })}</div></div>
    ${field("Note", `<div class="textarea"><span class="faint">What did you see?</span></div>`, "0 of 2000 characters")}</div>
  <footer>${btn("Cancel")}${btn("Add note", "primary")}</footer></div></div>`;

export default {
  file: "m12-type-log",
  title: "M12 Type detail: log",
  views: ["default", "note"],
  viewSpecs: [{ id: "default" }, { id: "note", kb: true }],
  modalViews: ["note"],
  css: `.entry2{display:flex;flex-direction:column;gap:6px;padding:14px 16px;border-bottom:1px solid var(--line)}.entry2:last-child{border-bottom:0}details summary{cursor:default;margin:4px 0}`,
  body: () => shell({
    active: "Sheet archive",
    content: `<div class="col g24"><div class="col g4"><div class="crumbs"><a href="#">Sheet archive</a><span>/</span><span>Avery Zweckform L4736REV</span></div><h1 class="title">Avery Zweckform L4736REV</h1>
      <div class="tabs" role="tablist"><span class="t">Measurements</span><span class="t">Sheet code</span><span class="t">Versions</span><span class="t">Sheets <span class="count">12</span></span><span class="t on">Log</span></div></div>${list}</div>
      <div data-only="note">${dlg}</div>`,
    notes: [
      "Spec 7.6 (#351): entries with kind, printer and tray, the correction in effect (linked to the history of M7), the readings per crossing, a verdict (fits, sheet geometry, feed variance, printer, none) and a note, written automatically by check prints, \"verified\", new versions and catalog updates, plus hand entries and the API.",
      "Per type, filtered by printer; text only, no photos (those wait for #333). Internal only: the banner says it never leaves the hub.",
      "View <code>note</code>: the hand-entry dialog on a phone with the keyboard open; the verdict list opens upward and is only as tall as the room above the field (it scrolls), so it stays inside the visible area.",
    ],
  }),
};
