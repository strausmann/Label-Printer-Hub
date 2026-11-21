// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
// M8 — Calibration page → Readings (spec 7.4).

import { badge, btn, field, icon, input, note, select, shell } from "../lib.mjs";
import { calHead } from "../parts.mjs";

const dirSeg = (opts, on) => `<div class="seg" role="radiogroup" style="align-self:stretch">${opts.map((o) => `<span class="opt${o === on ? " on" : ""}" style="flex:1" role="radio" aria-checked="${o === on}">${o}</span>`).join("")}</div>`;
const step = (v, { focus = false, bad = false } = {}) => `<div class="stepper${focus ? " is-focus" : ""}" style="${bad ? "border-color:var(--bad);box-shadow:inset 0 0 0 1px var(--bad);" : ""}align-self:stretch"><span class="sb">−</span><span class="val grow">${v}${focus ? '<i class="caret"></i>' : ""}<span class="unit">mm</span></span><span class="sb">+</span></div>`;

const reading = ({ n, s, z, ax, ad, dy, dd, focus, extra = "", warn = "", res }) => `<li class="panel col g16 rcard">
  <div class="row between wrap-row"><span class="row g8"><span class="bold">Reading ${n}</span><span class="row g8">${select(`S${s}`)}${select(`Z${z}`)}</span></span>${btn("Remove", "sm link-btn")}</div>
  <div class="grid2 keep">
    <div class="col g8"><span class="lbl">Across</span>${dirSeg(["Left of line", "Right of line"], ad)}${step(ax, { focus: focus === "ax", bad: warn })}${extra}</div>
    <div class="col g8"><span class="lbl">Down</span>${dirSeg(["Above", "Below"], dd)}${step(dy, { focus: focus === "dy" })}</div></div>
  ${warn ? `<p class="err">${icon("warn", 16)}<span>The print is off by more than the scale shows (±2.0 mm). Check the tray, the sheet type or the printer.</span></p>` : ""}</li>`;

const r1 = reading({ n: 1, s: 1, z: 1, ax: "0.4", ad: "Left of line", dy: "0.7", dd: "Below" });
const r2 = reading({ n: 2, s: 4, z: 6, ax: "0.4", ad: "Right of line", dy: "0.5", dd: "Above", focus: "ax", extra: `<p class="hint">You typed 0,43. Readings snap to 0.1 mm, so it is saved as 0.4 mm.</p>` });
const r3 = reading({ n: 3, s: 2, z: 12, ax: "2.6", ad: "Left of line", dy: "0.3", dd: "Below", warn: true });

const fit = `<div class="panel col g16"><div class="row between wrap-row"><h3 class="section">Live fit</h3>${badge("Updates as you type", "plain")}</div>
  <p class="small muted">Needs three readings. Recalculated 0.4 s after your last change.</p>
  <dl class="vgrid2"><div><dt class="small muted">Across</dt><dd class="mono bold">+0.41 mm</dd></div><div><dt class="small muted">Down</dt><dd class="mono bold">−0.66 mm</dd></div><div><dt class="small muted">Scale</dt><dd class="mono bold">+0.012 % / −0.008 %</dd></div><div><dt class="small muted">Rotation</dt><dd class="mono bold">+0.021°</dd></div></dl>
  <div class="table-wrap"><table class="tbl"><thead><tr><th>Crossing</th><th class="num">Residual</th><th></th></tr></thead><tbody>
   <tr><td class="mono bold">S1 · Z1</td><td class="num mono">0.08 mm</td><td>${badge("fits", "ok", "check")}</td></tr>
   <tr><td class="mono bold">S4 · Z6</td><td class="num mono">0.12 mm</td><td>${badge("fits", "ok", "check")}</td></tr>
   <tr style="background:var(--warn-soft)"><td class="mono bold">S2 · Z12</td><td class="num mono">0.41 mm</td><td>${badge("probable misread", "warn", "warn")}</td></tr></tbody></table></div>
  <p class="small muted">A residual over 0.3 mm is marked: read that crossing again before you save.</p></div>`;

const suggestion = `<div class="panel col g16" style="border-color:var(--link)"><div class="row between wrap-row"><h3 class="section">Geometry suggestion</h3>${badge("From 8 check readings", "info")}</div>
  <p>These readings were printed with the correction measured on <strong>Avery Zweckform 6121</strong>, a different type. What is left looks like the sheet, not the printer: across the columns the error grows evenly.</p>
  <dl class="vgrid2"><div><dt class="small muted">Pitch across</dt><dd class="mono bold">48.20 → 47.55 mm</dd></div><div><dt class="small muted">Left margin</dt><dd class="mono bold">9.85 → 9.90 mm</dd></div></dl>
  <div class="row g8 wrap-row">${btn("Apply as new version", "primary")}${btn("Fill the feedback issue")}</div>
  <p class="small muted">Adds version 2 of Avery Zweckform L4737REV with a change note naming print #12, and a log entry. Admins only. Sheets already made keep version 1.</p></div>
  <div class="note info" role="note">${icon("info", 18)}<div class="body"><strong>No suggestion for this one</strong><span>The saved correction was measured on this same type, so a pitch error would be absorbed into it. Print a check page on another sheet type first. An uneven pattern would read: \"check the sheet, not the printer\".</span></div></div>`;

const form = `<div class="col g16"><div class="col g4"><h2 class="section">Readings</h2><p class="muted">Enter how far the ink landed from each printed crossing. Use the direction buttons so the sign is never a guess.</p></div>
  <div class="grid2"><div class="field"><label>Readings from print</label>${select("#12 · calibration page · 2026-11-21 14:20")}<p class="hint">The newest page of this printer, tray and type. Printed from Tray 1 (manual feed), as requested.</p></div>
    <div class="field"><label>Step</label><div class="seg"><span class="opt">0.5 mm (the scale)</span><span class="opt on">0.1 mm</span></div><p class="hint">Estimate between two ticks to 0.1 mm.</p></div></div>
  <ul class="col g16" aria-label="Readings">${r1}${r2}${r3}</ul>
  <div class="row g8 wrap-row">${btn("Add reading", "", "plus")}${btn("Fit", "primary")}<span class="small muted">3 readings</span></div></div>`;

export default {
  file: "m08-calibration-readings",
  title: "M8 Calibration: readings",
  views: ["default", "entry"],
  viewSpecs: [{ id: "default" }, { id: "entry", kb: true }],
  modalViews: ["entry"],
  css: `.vgrid2{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px 16px;margin:0}.vgrid2 dd{margin:0}html[data-view="entry"] .tabbar{display:none}
  .sticky-act{position:sticky;bottom:0;display:flex;gap:8px;padding:10px 0 0;background:var(--bg);border-top:1px solid var(--line)}`,
  body: () => shell({
    active: "Calibration",
    content: `<div class="col g24" data-not="entry">${calHead("Readings")}<div class="split-wide wide-side"><div class="col g16">${form}</div><div class="col g16 stick">${fit}${suggestion}</div></div></div>
      <div class="col g16" data-only="entry">${calHead("Readings", { compact: true })}
        <ul class="col g16">${r2}</ul>
        <div class="sticky-act">${btn("Add reading", "", "plus")}${btn("Fit", "primary")}<span class="grow"></span></div></div>`,
    notes: [
      "Spec 7.4: a stepper that follows the scale but moves in 0.1 mm, an explicit direction picker per axis (the sign is never typed), a hint when a typed value snapped, a warning outside the scale, the run picker (\"Readings from print #12\"), the live fit with residuals and probable misreads, and the geometry suggestion with \"Apply as new version\".",
      "The geometry suggestion only exists when the saved correction was measured on another sheet type; the second card shows why it says no otherwise.",
      "View <code>entry</code> is the form on a phone with the keyboard open: the focused value, its direction picker and \"Fit\" stay in view; the live fit panel is below and does not push the field out (spec 12).",
    ],
  }),
};
