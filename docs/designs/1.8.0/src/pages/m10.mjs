// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
// M10 — Printers list and detail: the "Not wired" state (spec 9.3).

import { badge, btn, icon, note, shell } from "../lib.mjs";

const printers = [
  { n: "Office laser", m: "Page printer · IPP", a: "printer-1.example.invalid", st: "wired", on: true, tray: "Tray 1, Tray 2" },
  { n: "Desk inkjet", m: "Page printer · IPP", a: "printer-2.example.invalid", st: "not", reason: "The printer did not answer when the hub looked for it.", sel: true },
  { n: "Label tape QL-820NWB", m: "Tape printer · 62 mm endless", a: "tape-1.example.invalid", st: "wired", on: true },
  { n: "Archive laser", m: "Page printer · IPP", a: "printer-3.example.invalid", st: "disabled" },
];
const state = (p) => p.st === "wired" ? `${badge("Wired", "ok", "check")}${badge(p.on ? "Online" : "Offline", p.on ? "ok" : "plain")}` : p.st === "not" ? badge("Not wired", "bad", "x") : badge("Disabled", "plain");

const card = (p) => `<li class="item-card${p.sel ? " on" : ""}"><div class="row between wrap-row g8"><span class="bold">${p.n}</span><span class="row g8 wrap-row">${state(p)}</span></div>
  <span class="small muted">${p.m} · <span class="mono">${p.a}</span></span>
  ${p.st === "not" ? `<p class="small" style="color:var(--bad)">${icon("warn", 14)} Not wired: ${p.reason.toLowerCase().replace(/\.$/, "")}.</p><p class="small muted">Check the address, then save the printer again.</p>` : ""}</li>`;

const detail = `<div class="col g24"><div class="row between wrap-row"><div class="col g4"><h2 class="title">Desk inkjet</h2><span class="muted">Page printer · IPP · <span class="mono">printer-2.example.invalid</span></span></div><span class="row g8 wrap-row">${btn("Save printer again", "primary")}${btn("Edit address", "", "pencil")}</span></div>
  ${note("bad", "Not wired: the printer did not answer when the hub looked for it", "The hub started and carried on without it, so nothing else is held up. Pages for this printer cannot print until it is wired. Check the address and that the printer is switched on, then save the printer again: saving tries the connection again, you do not need to restart the hub.")}
  <div class="panel col g8"><h3 class="section">What the hub saw</h3><dl class="small" style="display:grid;grid-template-columns:auto 1fr;gap:4px 16px"><dt class="muted">State</dt><dd class="bold">Not wired</dd><dt class="muted">Reason</dt><dd>The printer did not answer when the hub looked for it <span class="mono small faint">discovery_failed</span></dd><dt class="muted">Last attempt</dt><dd>2026-11-21 08:12</dd><dt class="muted">After a restart</dt><dd>The hub tries again by itself.</dd></dl></div>
  <div class="panel col g8"><h3 class="section">The other reasons</h3><dl class="small" style="display:grid;grid-template-columns:auto 1fr;gap:4px 16px"><dt class="mono muted">model_unknown</dt><dd>The hub does not know this printer model.</dd><dt class="mono muted">invalid_config</dt><dd>The saved settings are not valid: open Edit address.</dd><dt class="mono muted">unexpected</dt><dd>Something unexpected stopped the connection. See Jobs and the hub log.</dd></dl></div></div>`;

export default {
  file: "m10-printer-not-wired",
  title: "M10 Printers: not wired",
  body: () => shell({
    active: "Printers", tab: "Printers",
    content: `<div class="col g24"><div class="row between wrap-row"><h1 class="title">Printers</h1>${btn("Add printer", "primary", "plus")}</div>
      ${note("bad", "1 printer is not wired", "Desk inkjet could not be reached when the hub started. Open it to see why and try again.")}
      <div class="split"><ul class="col g8" aria-label="Printers">${printers.map(card).join("")}</ul>${detail}</div></div>`,
    notes: [
      "Spec 9.3 (#401): the printer response gains <code>wiring</code> (wired, not_wired, disabled) and a fixed <code>wiring_reason</code> code; the UI shows the reason in words and never the exception text.",
      "Saving the printer re-attaches it (no restart). The state lives in memory only: a restart retries by itself.",
      "A disabled printer is a different, neutral state: it is switched off on purpose, not broken.",
    ],
  }),
};
