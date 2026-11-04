# Third-party notices

Label Printer Hub is MIT-licensed (see [LICENSE](LICENSE)). This file lists the runtime
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
| cryptography | Apache-2.0 OR BSD-3-Clause | AES-GCM encryption of stored integration secrets |
| greenlet | MIT AND PSF-2.0 | Required by SQLAlchemy's async engine (declared explicitly) |

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
| zxing-wasm | 3.1.6 | MIT | Wrapper; the `.wasm` it ships is zxing-cpp, Apache-2.0, text in `licenses/zxing-cpp-Apache-2.0.txt` |

The service worker is generated with Workbox (MIT) and `vite-plugin-pwa` (MIT) at build time.
Development-only dependencies (Vite, Vitest, Playwright, ESLint, Tailwind CSS, TypeScript and
similar) are not part of the image.

## Fonts

Atkinson Hyperlegible and Atkinson Hyperlegible Mono are licensed under the SIL Open Font
License 1.1. The fonts are not sold on their own and are not renamed.
