// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
// M11 — Settings → Integrations: public web URL (spec 9.4).

import { badge, btn, field, icon, input, note, shell } from "../lib.mjs";

const lockedInput = (v, env) => `<div class="input" style="background:var(--sunken);flex-wrap:wrap"><span class="mono wrap" style="font-size:13px">${v}</span><span class="row g8 small muted">${icon("lock", 16)}Set by ${env}</span></div>`;

const panel = ({ name, internal, env, web, err, focus, hint = true, compact = false }) => `<section class="panel col g16"><div class="row between wrap-row"><h2 class="section">${name}</h2>${err ? badge("Not saved", "bad", "x") : web ? badge("Links shown", "ok", "check") : badge("No links shown", "plain")}</div>
  ${compact ? "" : field("Address the hub uses", lockedInput(internal, env), "Internal. Only admins see this address.")}
  ${field("Public web address", input(web || "https://", { focus, invalid: !!err, ph: !web, caret: focus }), hint ? `The address people reach ${name} on. The hub builds the links in the app from it, and — once it is set — the QR codes on printed labels too. Empty: no link is shown, and printed codes keep working as they do now.` : "", err)}
  <div class="row g8 wrap-row">${btn("Save", "primary")}${btn("Clear")}</div></section>`;

const snipe = panel({ name: "Snipe-IT", internal: "http://snipeit.example.invalid:8080", env: "SNIPEIT_URL", web: "https://assets.example.com" });
const grocy = panel({ name: "Grocy", internal: "http://grocy.example.invalid:9283", env: "GROCY_URL", web: "https://user:secret@grocy.example.invalid", err: "Use an http or https address without a user name or password." });
const paper = panel({ name: "Paperless", internal: "http://paperless.example.invalid:8000", env: "PAPERLESS_URL", web: "" });

export default {
  file: "m11-integrations-web-url",
  title: "M11 Settings: public web URL",
  views: ["default", "field"],
  viewSpecs: [{ id: "default" }, { id: "field", kb: true }],
  modalViews: ["field"],
  css: `html[data-view="field"] .tabbar{display:none}html[data-view="field"] .panel>.row:last-child{position:sticky;bottom:0;background:var(--surface);padding-top:8px}`,
  body: () => shell({
    active: "Settings",
    content: `<div class="col g24"><div data-not="field" class="col g24"><h1 class="title">Settings</h1></div><div class="tabs" role="tablist"><span class="t">General</span><span class="t">Printers</span><span class="t on">Integrations</span><span class="t">Keys</span><span class="t">Notifications</span></div>
      <div data-not="field">${note("info", "Public web address", "Where an item's page lives for people, for example on your own domain. Without it the hub shows no \"Open in\" link. It never changes the address the hub itself uses to reach the integration.")}</div>
      <div class="grid2 wide1" data-not="field">${snipe}${grocy}${paper}</div>
      <div data-only="field" class="col g16">${panel({ name: "Grocy", internal: "http://grocy.example.invalid:9283", env: "GROCY_URL", web: "https://grocy.example", focus: true, compact: true })}</div></div>`,
    notes: [
      "Spec 9.4 (#247): the new <code>integrations.&lt;name&gt;.web_url</code> setting per integration. Validated http/https, no user name or password, at most 2048 characters; it can be locked by an environment variable like the others.",
      "Snipe-IT is filled in, Grocy shows the refusal for an address with a user name, Paperless is empty (no link shown). The internal address is read-only and only an admin sees it.",
      "View <code>field</code>: the field with the keyboard open; the explanation stays beside it and Save is reachable.",
    ],
  }),
};
