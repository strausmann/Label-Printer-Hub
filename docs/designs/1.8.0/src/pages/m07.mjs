// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
// M7 — Calibration page → History (spec 7.1, 7.5).

import { badge, btn, field, icon, input, note, shell } from "../lib.mjs";
import { calHead } from "../parts.mjs";

const vals = (v, d = {}) => `<dl class="vgrid">${[["Across", v[0], "mm", d[0]], ["Down", v[1], "mm", d[1]], ["Scale across", v[2], "%", d[2]], ["Scale down", v[3], "%", d[3]], ["Rotation", v[4], "°", d[4]]]
  .map(([l, x, u, df]) => `<div><dt class="small muted">${l}</dt><dd class="mono bold">${x}<span class="faint small"> ${u}</span></dd>${df && !/^[+−]?0\.0+$/.test(df) ? `<dd class="small muted">${df} <span class="faint">vs. before</span></dd>` : ""}</div>`).join("")}</dl>`;

const entry = (e) => `<li class="entry${e.now ? " now" : ""}">
  <div class="row between wrap-row g8"><span class="row g8 wrap-row"><span class="seq mono">${e.seq}</span>${e.badge}${e.now ? badge("In use now", "ok", "check") : ""}<span class="small muted">${e.when} · ${e.who}</span></span>
    ${e.now ? "" : btn("Restore these values", "sm", "undo")}</div>
  ${vals(e.v, e.d)}
  <p class="small">${e.how}</p>
  ${e.note ? `<p class="small muted">Note: ${e.note}</p>` : ""}
  <div class="row g16 wrap-row small"><a href="#">${e.jobs} jobs printed with it</a>${e.readings ? `<a href="#">${e.readings}</a>` : ""}</div></li>`;

const entries = [
  { seq: 4, badge: badge("Revert", "info", "undo"), now: true, when: "2026-11-21 14:05", who: "admin", v: ["+0.41", "−0.66", "+0.012", "−0.008", "+0.021"], d: ["+0.03", "−0.04", "0.000", "0.000", "0.000"], how: "Restored from entry 2. Measured on Avery Zweckform 6121 v1.", note: "The new tray feed drifted back; entry 3 was a bad fit.", jobs: 3 },
  { seq: 3, badge: badge("Save", "plain"), when: "2026-11-20 18:22", who: "admin", v: ["+0.38", "−0.62", "+0.012", "−0.008", "+0.021"], d: ["−0.03", "+0.04", "0.000", "0.000", "0.000"], how: "Fit from 12 readings of print #12 · largest residual 0.18 mm. Measured on Avery Zweckform 6121 v1.", jobs: 5, readings: "12 readings · print #12" },
  { seq: 2, badge: badge("Save", "plain"), when: "2026-11-15 10:40", who: "admin", v: ["+0.41", "−0.66", "+0.012", "−0.008", "+0.021"], d: ["+0.41", "−0.66", "+0.012", "−0.008", "+0.021"], how: "Typed by hand, no readings. Measured on Avery Zweckform L4731REV v2.", jobs: 14 },
  { seq: 1, badge: badge("Imported", "plain", "history"), when: "before 1.8.0", who: "—", v: ["0.00", "0.00", "0.000", "0.000", "0.000"], how: "The correction this tray had when 1.8.0 was installed. It had no readings.", jobs: 0 },
];

const runs = [
  ["#14", "Check page", "2026-11-21 14:44", "Tray 1 (manual feed)", "Tray 1 (manual feed)", ""],
  ["#13", "Check page", "2026-11-21 14:32", "Tray 1 (manual feed)", "Tray 2", "warn"],
  ["#12", "Calibration page", "2026-11-21 14:20", "Tray 1 (manual feed)", "not reported", ""],
  ["#11", "Probe page (retry)", "2026-11-20 18:02", "Tray 1 (manual feed)", "Tray 1 (manual feed)", ""],
];

const runsHtml = `<div class="table-wrap"><table class="tbl cards"><thead><tr><th>Run</th><th>Page</th><th>Printed</th><th>Requested tray</th><th>Printed from</th></tr></thead><tbody>${runs.map(([n, k, t, rq, ac, w]) => `<tr><td data-l="Run" class="bold mono">${n}</td><td data-l="Page">${k}</td><td data-l="Printed" class="tnum">${t}</td><td data-l="Requested">${rq}</td><td data-l="Printed from">${w ? badge(ac, "warn", "warn") : ac === "not reported" ? `<span class="muted">not reported by the printer</span>` : ac}</td></tr>`).join("")}</tbody></table></div>`;

const dlg = `<div class="scrim" role="dialog" aria-modal="true" aria-labelledby="rs-h"><div class="dialog">
  <header><h2 id="rs-h">Use these values again?</h2><p class="muted small">Office laser · Tray 1 (manual feed). This adds a new entry; nothing is deleted.</p></header>
  <div class="body"><div class="panel flat"><dl class="vgrid" style="grid-template-columns:repeat(2,minmax(0,1fr))"><div><dt class="small muted">Across</dt><dd class="mono bold">+0.41 mm</dd></div><div><dt class="small muted">Down</dt><dd class="mono bold">−0.66 mm</dd></div><div><dt class="small muted">Scale</dt><dd class="mono bold">+0.012 % / −0.008 %</dd></div><div><dt class="small muted">Rotation</dt><dd class="mono bold">+0.021°</dd></div></dl></div>
    ${field("Note (optional)", `<div class="input is-focus"><span class="grow">Back to the values of 11-15<i class="caret"></i></span></div>`, "Kept in the history with who restored it.")}</div>
  <footer>${btn("Cancel")}${btn("Use these values", "primary")}</footer></div></div>`;

export default {
  file: "m07-calibration-history",
  title: "M7 Calibration: history",
  views: ["default", "restore"],
  viewSpecs: [{ id: "default" }, { id: "restore", kb: true }],
  modalViews: ["restore"],
  css: `.vgrid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px 16px;margin:0}.vgrid dd{margin:0}.entry{display:flex;flex-direction:column;gap:8px;padding:16px;border-bottom:1px solid var(--line)}.entry:last-child{border-bottom:0}.entry.now{background:var(--sunken)}.seq{display:inline-flex;align-items:center;justify-content:center;min-width:28px;height:28px;border-radius:50%;background:var(--ink);color:var(--surface);font-size:13px}
  @media (max-width:639px){.vgrid{grid-template-columns:repeat(2,minmax(0,1fr))}}`,
  body: () => shell({
    active: "Calibration",
    content: `<div class="col g24">${calHead("History")}
      ${note("warn", "Print #13 came from Tray 2", "You asked for Tray 1 (manual feed) but the printer reported that the page was fed from Tray 2. The correction you save from it belongs to Tray 2.")}
      <section class="col g16"><div class="col g4"><h2 class="section">Corrections for this tray</h2><p class="muted">Every save is kept. Restoring an entry adds a new one; nothing is overwritten or deleted.</p></div>
        <ul class="table-wrap" aria-label="History">${entries.map(entry).join("")}</ul>
        <p class="small muted">Showing 4 of 4 entries. The hub keeps the newest 500 per printer and tray.</p></section>
      <section class="col g16"><div class="col g4"><h2 class="section">Pages printed from this tray</h2><p class="muted">Every calibration, check and probe page has a run number. A retry keeps its number.</p></div>${runsHtml}</section></div>
      <div data-only="restore">${dlg}</div>`,
    notes: [
      "Spec 7.5: entries per tray with the difference to the previous one, the jobs-printed-with-it link, the readings and print they came from, a note, and \"Restore these values\" (admin) that names the values in its confirmation.",
      "Spec 7.1: the run list shows requested and actual tray from the printer (IPP); a mismatch is a warning, a printer that does not report it says so.",
      "The first entry is the correction the tray had when 1.8.0 was installed (action <code>imported</code>, no readings).",
    ],
  }),
};
