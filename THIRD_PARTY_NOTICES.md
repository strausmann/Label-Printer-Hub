# Third-party notices

Label Printer Hub is licensed under AGPL-3.0-or-later (see [LICENSE](LICENSE)). This file lists the runtime
dependencies added by the single-container web UI release and the licence each one carries.
The image ships it as `/opt/app/THIRD_PARTY_NOTICES.md`; the licence texts that must travel
with the web app's fonts and barcode reader are in the web app's `licenses/` folder
(`/opt/app/web/licenses/` in the image).

Automatic generation of the complete list, including transitive dependencies, is tracked
in [#154](https://github.com/strausmann/Label-Printer-Hub/issues/154). Until then this list
covers the direct runtime dependencies this release added.

## Backend (Python)

| Package | Licence | Why |
|---|---|---|
| charset-normalizer | MIT | Pulled in by reportlab (transitive dependency) |
| cryptography | Apache-2.0 OR BSD-3-Clause | AES-GCM encryption of stored integration secrets |
| greenlet | MIT AND PSF-2.0 | Required by SQLAlchemy's async engine (declared explicitly) |
| reportlab | BSD-3-Clause | PDF pages for page printers |

## Fonts bundled in the backend

| Font | Licence | Notes |
|---|---|---|
| DejaVu Sans (`DejaVuSans.ttf`, Debian `fonts-dejavu-core` 2.37) | Bitstream Vera licence (DejaVu changes are public domain) | Embedded as a subset in the PDF pages for page printers. The file and its licence text ship in the package as `app/page_render/fonts/DejaVuSans.ttf` and `app/page_render/fonts/LICENSE-DejaVu.txt` |

## Web app (npm, bundled into `dist`)

| Package | Version | Licence | Notes |
|---|---|---|---|
| @fontsource/atkinson-hyperlegible | 5.3.0 | OFL-1.1 | Font files in `dist/assets`; text in `licenses/atkinson-hyperlegible-OFL-1.1.txt` |
| @fontsource/atkinson-hyperlegible-mono | 5.3.0 | OFL-1.1 | Font files in `dist/assets`; text in `licenses/atkinson-hyperlegible-mono-OFL-1.1.txt` |
| @lingui/core | 6.12.0 | MIT | Translations |
| @lingui/react | 6.12.0 | MIT | Translations |
| @tanstack/react-query | 5.105.3 | MIT | Server state |
| @tanstack/react-router | 1.170.46 | MIT | Routing |
| react | 19.3.1 | MIT | UI |
| react-aria-components | 1.22.1 | Apache-2.0 | Accessible components (with its `@react-aria/*`, `@react-stately/*` and `@internationalized/*` packages) |
| react-dom | 19.3.1 | MIT | UI |
| @scalar/api-reference | 1.77.0 | MIT | Interactive API reference at `/docs`; the standalone bundle is served from `dist/scalar/` (no CDN), text in `licenses/scalar-api-reference-MIT.txt` |
| zxing-wasm | 3.1.6 | MIT | Wrapper; the `.wasm` it ships is zxing-cpp, Apache-2.0, text in `licenses/zxing-cpp-Apache-2.0.txt` |

The service worker is generated with Workbox (MIT) and `vite-plugin-pwa` (MIT) at build time.
Development-only dependencies (Vite, Vitest, Playwright, ESLint, Tailwind CSS, TypeScript and
similar) are not part of the image.

## Sheet type data

The label sheet geometries in `backend/app/seed/sheet_types.json` were derived from the
template files of [gLabels-qt](https://github.com/j-evins/glabels-qt) at commit `37901c1`,
which are licensed under the MIT licence:

```text
Copyright (C) 2001-2026 Jaye Evins

Permission is hereby granted, free of charge, to any person obtaining a copy of this software
and associated documentation files (the "Software"), to deal in the Software without
restriction, including without limitation the rights to use, copy, modify, merge, publish,
distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the
Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or
substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING
BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM,
DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
```

The entries for L4731REV and L4736REV cite Labelplanet and MR-Label as sources of facts
(measurements) only; no text or files from those sites are included.

## Fonts

Atkinson Hyperlegible and Atkinson Hyperlegible Mono are licensed under the SIL Open Font
License 1.1. The fonts are not sold on their own and are not renamed.
