// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

// Helpers shared by the mockup pages: icons, the app shell, form pieces and the sheet drawing.
// Pages are plain template strings; build.mjs turns them into self-contained HTML files.

// ---------- icons (paths copied from frontend/src/shell/icons.tsx, 24 px grid, stroke 1.75) ----------
const I = {
  overview: '<rect x="3.5" y="3.5" width="7" height="8" rx="1.5"/><rect x="13.5" y="3.5" width="7" height="5" rx="1.5"/><rect x="13.5" y="11.5" width="7" height="9" rx="1.5"/><rect x="3.5" y="14.5" width="7" height="6" rx="1.5"/>',
  printers: '<path d="M7 9V4h10v5"/><rect x="3.5" y="9" width="17" height="8" rx="2"/><rect x="7" y="14" width="10" height="6" rx="1"/>',
  jobs: '<path d="M8 6h12M8 12h12M8 18h12"/><path d="M3.5 6h.01M3.5 12h.01M3.5 18h.01"/>',
  sheets: '<rect x="4" y="3.5" width="16" height="17" rx="2"/><path d="M4 9.5h16M10 9.5v11"/>',
  archive: '<rect x="3.5" y="4" width="17" height="4.5" rx="1"/><path d="M5 8.5V19a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8.5M10 12.5h4"/>',
  calibration: '<path d="M3.5 17.5h17M6 17.5v-3M10 17.5v-5M14 17.5v-3M18 17.5v-5"/><path d="M5 8l14-3"/>',
  document: '<path d="M7 3.5h7l4 4V20a.5.5 0 0 1-.5.5h-10.5a.5.5 0 0 1-.5-.5V4a.5.5 0 0 1 .5-.5Z"/><path d="M14 3.5V8h4M9 13h6M9 16.5h4"/>',
  link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3A4 4 0 0 0 11 18.7l1-1"/>',
  settings: '<path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/>',
  scan: '<path d="M4 8V5.5A1.5 1.5 0 0 1 5.5 4H8M16 4h2.5A1.5 1.5 0 0 1 20 5.5V8M20 16v2.5a1.5 1.5 0 0 1-1.5 1.5H16M8 20H5.5A1.5 1.5 0 0 1 4 18.5V16"/><path d="M4 12h16"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="m16 16 4 4"/>',
  close: '<path d="m6 6 12 12M18 6 6 18"/>',
  menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
  bell: '<path d="M6 16.5V11a6 6 0 0 1 12 0v5.5l1.5 1.5h-15L6 16.5Z"/><path d="M10 20.5a2.2 2.2 0 0 0 4 0"/>',
  cart: '<path d="M3 4h2.4l2.2 10.5h9.8L19.5 8H6.4"/><circle cx="9.5" cy="19" r="1.3"/><circle cx="16.5" cy="19" r="1.3"/>',
  info: '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5.5M12 7.8h.01"/>',
  check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
  warn: '<path d="M12 4 21 19.5H3L12 4Z"/><path d="M12 10v4.5M12 17h.01"/>',
  x: '<circle cx="12" cy="12" r="8.5"/><path d="m9 9 6 6M15 9l-6 6"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  trash: '<path d="M4.5 7h15M9.5 7V4.5h5V7M6.5 7l1 12.5h9l1-12.5M10 11v5M14 11v5"/>',
  lock: '<rect x="5" y="10.5" width="14" height="9.5" rx="2"/><path d="M8 10.5V8a4 4 0 0 1 8 0v2.5"/>',
  undo: '<path d="M9 7 4.5 11.5 9 16"/><path d="M5 11.5h8.5a5 5 0 0 1 0 10H11"/>',
  chevron: '<path d="m7 10 5 5 5-5"/>',
  external: '<path d="M14 4.5h5.5V10M19.5 4.5 11 13M17 14v4.5a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 5 18.5v-9A1.5 1.5 0 0 1 6.5 8H10"/>',
  qr: '<path d="M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h2.5v2.5H14zM18 14h2v2h-2zM14 18h2v2h-2zM18 18h2v2h-2z"/>',
  history: '<path d="M4 12a8 8 0 1 0 2.6-5.9"/><path d="M4 4.5V9h4.5M12 7.5V12l3 2"/>',
  tray: '<path d="M4 15.5h16l-1.5 4h-13zM7 15.5V9l5-4 5 4v6.5"/>',
  pencil: '<path d="m5 19 1-4L16.5 4.5a2 2 0 0 1 3 3L9 18l-4 1Z"/>',
  filter: '<path d="M4 6h16M7 12h10M10 18h4"/>',
  wifi: '<path d="M4 9.5a12 12 0 0 1 16 0M7 13a7.5 7.5 0 0 1 10 0M10.2 16.4a3 3 0 0 1 3.6 0M12 19.5h.01"/>',
  asset: '<path d="M3.5 12.2V4.5a1 1 0 0 1 1-1h7.7a1 1 0 0 1 .7.3l7.3 7.3a1 1 0 0 1 0 1.4l-7.7 7.7a1 1 0 0 1-1.4 0l-6.9-6.9a1 1 0 0 1-.7-.7Z"/><circle cx="8" cy="8" r="1.4"/>',
  clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
  eye: '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z"/><circle cx="12" cy="12" r="2.8"/>',
};

export function icon(name, size = 18, cls = "") {
  return `<svg viewBox="0 0 24 24" width="${size}" height="${size}" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false" class="${cls}">${I[name]}</svg>`;
}

const MARK = `<svg viewBox="0 0 64 64" role="img" aria-label="Labelyard"><title>Labelyard</title><rect width="64" height="64" rx="14" fill="#0B1429"/><g transform="rotate(14 32 32) translate(32 32) scale(1.1) translate(-32 -32)"><path d="M26,9H38L44,16V51a3,3 0 0 1-3,3H23a3,3 0 0 1-3-3V16Z" fill="#3F73EC"/><path d="M32,22C32,25.5 27.2,25.5 27.2,29.5V46.2H39" fill="none" stroke="#FDFCF9" stroke-width="4.8" stroke-linecap="butt" stroke-linejoin="miter"/><circle cx="32" cy="18.2" r="4" fill="#0B1429"/></g></svg>`;

// ---------- app shell ----------
const NAV = [
  { id: "main", items: [["overview", "Overview"], ["printers", "Printers"], ["jobs", "Jobs"]] },
  { id: "Material", items: [["sheets", "Sheets"], ["archive", "Sheet archive"], ["calibration", "Calibration"]] },
  { id: "Integrations", items: [["document", "ASN labels"], ["link", "Kept"]] },
  { id: "System", items: [["settings", "Settings"]] },
];
const ICON_OF = { Overview: "overview", Printers: "printers", Jobs: "jobs", Sheets: "sheets", "Sheet archive": "archive", Calibration: "calibration", "ASN labels": "document", Kept: "link", Settings: "settings" };

/** The app around a page. `active` is the sidebar label; `tab` the phone tab that is lit (or none). */
export function shell({ active, tab = "Sheets", content, notes = [] }) {
  const nav = NAV.map(
    (g) =>
      `${g.id === "main" ? "" : `<p class="grp">${g.id}</p>`}<ul>${g.items
        .map(([ic, label]) => `<li><a class="nav-item${label === active ? " active" : ""}" href="#">${icon(ic, 22)}<span>${label}</span></a></li>`)
        .join("")}</ul>`,
  ).join("");
  const tabs = [["overview", "Overview"], ["printers", "Printers"], null, ["jobs", "Jobs"], ["sheets", "Sheets"]]
    .map((t) =>
      t === null
        ? `<a class="tab scan" href="#"><span class="disc">${icon("scan", 28)}</span><span>Scan</span></a>`
        : `<a class="tab${t[1] === tab ? " active" : ""}" href="#">${icon(t[0], 24)}<span>${t[1]}</span></a>`,
    )
    .join("");
  return `
<div class="app">
  <aside class="sidebar">
    <a class="brand" href="#">${MARK}<span>Labelyard</span></a>
    <nav aria-label="Main">${nav}</nav>
    <div class="foot">Connected · v1.8.0<br><a href="#">About and licences</a></div>
  </aside>
  <div class="main-col">
    <header class="topbar">
      <button class="icon-btn menu-btn" aria-label="Menu">${icon("menu", 24)}</button>
      <span class="brand-mini">${MARK}<span>Labelyard</span></span>
      <div class="search">${icon("search", 20)}<span>Search items, sheets, printers</span></div>
      <span class="spacer"></span>
      <a class="btn primary hide-narrow" href="#">${icon("scan", 20)} Scan</a>
      <button class="icon-btn" aria-label="Cart">${icon("cart", 24)}</button>
      <button class="icon-btn" aria-label="Notifications">${icon("bell", 24)}</button>
    </header>
    <main id="content">${content}</main>
    ${notes.length ? mockNotes(notes) : ""}
    <nav class="tabbar" aria-label="Tabs">${tabs}</nav>
  </div>
</div>`;
}

export function mockNotes(items) {
  return `<aside class="mock-notes"><h2>Mockup notes (not part of the app)</h2><ul>${items.map((n) => `<li>${n}</li>`).join("")}</ul></aside>`;
}

// ---------- small components ----------
export const badge = (text, kind = "", ic = "") => `<span class="badge ${kind}">${ic ? icon(ic, 14) : ""}${text}</span>`;
export const note = (kind, title, text, ic) =>
  `<div class="note ${kind}" role="note">${icon(ic ?? (kind === "bad" ? "x" : kind === "warn" ? "warn" : kind === "ok" ? "check" : "info"), 18)}<div class="body">${title ? `<strong>${title}</strong>` : ""}<span>${text}</span></div></div>`;
export const field = (label, control, hint = "", err = "") =>
  `<div class="field"><label>${label}</label>${control}${err ? `<p class="err">${icon("x", 16)}<span>${err}</span></p>` : ""}${hint ? `<p class="hint">${hint}</p>` : ""}</div>`;
export const input = (value, { unit = "", focus = false, invalid = false, ph = false, caret = false } = {}) =>
  `<div class="input${focus ? " is-focus" : ""}${invalid ? " invalid" : ""}"><span class="${ph ? "faint" : ""}">${value}${caret ? '<i class="caret"></i>' : ""}</span>${unit ? `<span class="unit">${unit}</span>` : ""}</div>`;
export const select = (value, { focus = false, up = false } = {}) => `<div class="select${focus ? " is-focus" : ""}${up ? " up" : ""}"><span>${value}</span></div>`;
export const seg = (opts, on) => `<div class="seg" role="radiogroup">${opts.map((o) => `<span class="opt${o === on ? " on" : ""}" role="radio" aria-checked="${o === on}">${o}</span>`).join("")}</div>`;
export const stepper = (val, unit = "mm", { focus = false } = {}) =>
  `<div class="stepper${focus ? " is-focus" : ""}"><span class="sb" aria-label="Less">−</span><span class="val">${val}<span class="unit">${unit}</span></span><span class="sb" aria-label="More">+</span></div>`;
export const checkbox = (label, on = false) => `<span class="check"><span class="box${on ? " on" : ""}">${on ? icon("check", 14) : ""}</span><span>${label}</span></span>`;
export const btn = (label, kind = "", ic = "") => `<a class="btn ${kind}" href="#">${ic ? icon(ic, 18) : ""}${label}</a>`;

// ---------- the sheet drawing ----------
/** Geometries of the demo types (values from backend/app/seed/sheet_types.json). */
export const GEOM = {
  l4736: { key: "avery-zweckform-l4736rev", name: "Avery Zweckform L4736REV", w: 210, h: 297, cols: 4, rows: 12, lw: 45.7, lh: 21.2, px: 48.2, py: 21.2, mt: 21.3, ml: 9.85, r: 1.5 },
  z6121: { key: "avery-zweckform-6121", name: "Avery Zweckform 6121", w: 210, h: 297, cols: 5, rows: 13, lw: 38.1, lh: 21.18, px: 38.1, py: 21.18, mt: 10.8, ml: 9.9, r: 1.2 },
  l4731: { key: "avery-zweckform-l4731rev", name: "Avery Zweckform L4731REV", w: 210, h: 297, cols: 7, rows: 27, lw: 25.4, lh: 9.98, px: 27.9, py: 9.98, mt: 12.54, ml: 8.6, r: 1.5 },
  z3490: { key: "avery-zweckform-3490", name: "Avery Zweckform 3490", w: 210, h: 297, cols: 3, rows: 8, lw: 70, lh: 36, px: 70, py: 36, mt: 4.5, ml: 0, r: 0 },
};

export function cellRect(g, n) {
  const row = Math.floor((n - 1) / g.cols);
  const col = (n - 1) % g.cols;
  return { x: g.ml + col * g.px, y: g.mt + row * g.py, w: g.lw, h: g.lh, row, col };
}

let uid = 0;
/**
 * A drawing of a sheet front in mm. `view` crops it ([x, y, w, h]). Layers, bottom to top: hardware margin, free bands,
 * labels, preprint zones (hatched), refused zones (red, dashed), the sheet-ID rectangle.
 */
export function sheetSvg({ g, view = [0, 0, 210, 297], zones = [], badZones = [], idRect = null, idNo = null, hw = null, bands = [], cellClass = "sv-cell", numbers = false, only = null, feed = null, width = null, label = "", extra = "", fs = 2.6 }) {
  const id = `p${++uid}`;
  const [vx, vy, vw, vh] = view;
  const sw = Math.max(vw, vh) / 600 + 0.12;
  let s = `<svg class="sheet-svg" viewBox="${vx} ${vy} ${vw} ${vh}" role="img" aria-label="${label || "Sheet drawing"}"${width ? ` style="max-width:${width}px"` : ""}><defs>
    <pattern id="${id}h" patternUnits="userSpaceOnUse" width="1.7" height="1.7" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="1.7" stroke="var(--ink-3)" stroke-width="0.45"/></pattern>
    <pattern id="${id}b" patternUnits="userSpaceOnUse" width="1.7" height="1.7" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="1.7" stroke="var(--bad)" stroke-width="0.5"/></pattern></defs>`;
  s += `<rect class="sv-page" x="0" y="0" width="${g.w}" height="${g.h}" stroke-width="${sw}"/>`;
  if (hw) s += `<path class="sv-hw" fill-rule="evenodd" d="M0 0H${g.w}V${g.h}H0Z M${hw.l} ${hw.t}V${g.h - hw.b}H${g.w - hw.r}V${hw.t}Z"/>`;
  for (const b of bands) s += `<rect class="sv-band" x="${b.x}" y="${b.y}" width="${b.w}" height="${b.h}"/>`;
  const total = g.cols * g.rows;
  for (let n = 1; n <= total; n++) {
    const r = cellRect(g, n);
    if (r.x > vx + vw || r.x + r.w < vx || r.y > vy + vh || r.y + r.h < vy) continue;
    const cls = typeof cellClass === "function" ? cellClass(n) : cellClass;
    if (only && !only.includes(n)) continue;
    s += `<rect class="${cls}" x="${r.x}" y="${r.y}" width="${r.w}" height="${r.h}" rx="${g.r}" stroke-width="${sw}"/>`;
    if (numbers) s += `<text class="sv-t b" x="${r.x + r.w / 2}" y="${r.y + r.h / 2 + fs * 0.35}" font-size="${fs}" text-anchor="middle">${n}</text>`;
  }
  for (const z of zones) s += `<rect class="sv-zone" x="${z.x}" y="${z.y}" width="${z.w}" height="${z.h}" stroke-width="${sw}" style="fill:url(#${id}h)"/>`;
  for (const z of badZones) s += `<rect class="sv-zone-bad" x="${z.x}" y="${z.y}" width="${z.w}" height="${z.h}" stroke-width="${sw * 1.4}" style="fill:url(#${id}b)"/>`;
  if (idRect) s += `<rect class="sv-id" x="${idRect.x}" y="${idRect.y}" width="${idRect.w}" height="${idRect.h}" stroke-width="${sw * 1.8}"/>`;
  if (idNo) s += `<rect class="sv-id-no" x="${idNo.x}" y="${idNo.y}" width="${idNo.w}" height="${idNo.h}" stroke-width="${sw * 1.6}"/>`;
  if (feed) s += `<rect class="sv-feed" x="${feed.x}" y="${feed.y}" width="${feed.w}" height="${feed.h}"/>`;
  s += extra;
  return s + "</svg>";
}

/** Demo preprint of an Avery Zweckform L4736REV top band (illustrative, NOT measured: the real preset waits for the photos of #246). */
export const DEMO_ZONES = [
  { x: 10, y: 6.5, w: 34, h: 9, note: "Logo" },
  { x: 49, y: 7.5, w: 51, h: 7, note: "Product description" },
  { x: 150, y: 7.5, w: 48, h: 7, note: "Size text" },
  { x: 10, y: 288.4, w: 190, h: 5, note: "Bottom line" },
];
export const DEMO_ID = { x: 104.2, y: 6, w: 42, h: 12 };
export const TOP_BAND = [{ x: 0, y: 4.2, w: 210, h: 16.1 }];
