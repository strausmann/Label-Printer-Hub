// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// Builds the self-contained mockup pages: node build.mjs [m01 m02 ...]
// Fonts come from frontend/node_modules/@fontsource (run `pnpm install` in frontend/ first) and are inlined as base64.

import { readFileSync, writeFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const out = join(here, "..");
const fonts = join(here, "../../../../frontend/node_modules/@fontsource");

const face = (family, weight, file) =>
  `@font-face{font-family:"${family}";font-weight:${weight};font-style:normal;font-display:block;src:url(data:font/woff2;base64,${readFileSync(join(fonts, file)).toString("base64")}) format("woff2")}`;
const FONT_CSS = [
  face("Atkinson Hyperlegible", 400, "atkinson-hyperlegible/files/atkinson-hyperlegible-latin-400-normal.woff2"),
  face("Atkinson Hyperlegible", 700, "atkinson-hyperlegible/files/atkinson-hyperlegible-latin-700-normal.woff2"),
  face("Atkinson Hyperlegible Mono", 400, "atkinson-hyperlegible-mono/files/atkinson-hyperlegible-mono-latin-400-normal.woff2"),
  face("Atkinson Hyperlegible Mono", 600, "atkinson-hyperlegible-mono/files/atkinson-hyperlegible-mono-latin-600-normal.woff2"),
].join("\n");
const SHARED = readFileSync(join(here, "shared.css"), "utf8").replace(/\/\*[\s\S]*?\*\//, "");

// ?theme=dark|light, ?view=<name>, ?shot (hides the mockup bar). Elements with data-only="a b" show only in those views.
const BOOT = `(function(){var q=new URLSearchParams(location.search),r=document.documentElement;var t=q.get("theme");if(t)r.setAttribute("data-theme",t);
var v=q.get("view")||"default";r.setAttribute("data-view",v);if((window.__modal||[]).indexOf(v)>=0)r.setAttribute("data-modal","");if(q.has("shot"))r.classList.add("shot");
document.addEventListener("DOMContentLoaded",function(){document.querySelectorAll("[data-only]").forEach(function(e){if(e.getAttribute("data-only").split(" ").indexOf(v)<0)e.hidden=true});
document.querySelectorAll("[data-not]").forEach(function(e){if(e.getAttribute("data-not").split(" ").indexOf(v)>=0)e.hidden=true});
var b=document.querySelector(".mock-bar");if(b){var s=location.pathname;b.innerHTML='<a href="'+s+'?theme=light&view='+v+'">Light</a><a href="'+s+'?theme=dark&view='+v+'">Dark</a>'+(window.__views||[]).map(function(x){return '<a href="'+s+'?view='+x+(t?'&theme='+t:'')+'">'+x+'</a>'}).join("")}});})();`;

export function render(page) {
  const views = page.views ?? ["default"];
  return `<!doctype html>
<!-- SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover, interactive-widget=resizes-content">
<title>${page.title} — Labelyard 1.8.0 mockup</title>
<style>${FONT_CSS}</style>
<style>${SHARED}</style>
<style>${page.css ?? ""}</style>
<script>window.__views=${JSON.stringify(views)};window.__modal=${JSON.stringify(page.modalViews ?? [])};${BOOT}</script>
</head>
<body>
${page.body()}
<div class="mock-bar" aria-hidden="true"></div>
</body>
</html>
`;
}

const only = process.argv.slice(2);
const files = readdirSync(join(here, "pages")).filter((f) => f.endsWith(".mjs") && (only.length === 0 || only.some((o) => f.startsWith(o))));
for (const f of files) {
  const page = (await import(pathToFileURL(join(here, "pages", f)).href)).default;
  writeFileSync(join(out, `${page.file}.html`), render(page));
  console.log("built", page.file);
}
