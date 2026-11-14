<!--
SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
SPDX-License-Identifier: AGPL-3.0-or-later
-->

# Decision register

Short, stable labels for decisions that code follows. A comment such as `# D4` or `// D5` marks a line that exists because of that decision, so related code can be found by searching for the label. Architecture decisions with a full rationale live in the [ADRs](README.md); the register is the index from label to decision.

Label kinds: `D<n>` decision, `V<n>` assumption still to be verified, `L<n>` lesson learned. Changing a decided behaviour adds a new label that supersedes the old one; old rows stay. The register is public by design (D9).

A guard test (`backend/tests/unit/test_decision_register.py`) fails if a `D<n>` label appears in `backend/app` or `frontend/src` without a row here, if a label is duplicated, or if an ADR link does not resolve.

| Label | Title | Date | Status | ADR |
|---|---|---|---|---|
| D1 | The single backend process serves the UI | 2026-11-04 | Accepted | [0015](0015-single-process-deployment.md) |
| D2 | React + TypeScript web UI stack | 2026-11-04 | Accepted | [0016](0016-react-typescript-web-ui.md) |
| D3 | Design token set (spec section 5.2) | 2026-11-04 | Accepted | [0022](0022-design-system-and-app-layout.md) |
| D4 | Environment variables win over stored settings and lock the field | 2026-11-04 | Accepted | [0017](0017-settings-in-database-env-locks-encrypted-secrets.md) |
| D5 | Secrets are encrypted with `LABELYARD_SECRET_KEY` and write-only | 2026-11-04 | Accepted | [0017](0017-settings-in-database-env-locks-encrypted-secrets.md) |
| D6 | Printers are managed in the UI | 2026-11-04 | Accepted | — |
| D7 | One-time bootstrap key plus container recovery command | 2026-11-04 | Accepted | [0017](0017-settings-in-database-env-locks-encrypted-secrets.md) |
| D8 | English is the default UI language | 2026-11-04 | Accepted | — |
| D9 | The decision register is public | 2026-11-04 | Accepted | [0018](0018-decision-register.md) |
| D10 | Proxy headers are trusted only with the trust token; legacy header and Basic bypass are opt-in | 2026-11-04 | Accepted | [0019](0019-proxy-headers-need-trust-token.md) |
| D11 | No global part-size or half-cut setting in the foundation | 2026-11-04 | Accepted | — |
| D12 | `ink-500` is `#6B655A` to meet WCAG AA contrast | 2026-11-04 | Accepted | — |
| D20 | The hub is AGPL-3.0-or-later and links to the source of the running build | 2026-11-05 | Accepted | — |
| D13 | Sheet archive, physical sheets and calibration live in the hub (#150) | 2026-11-05 | Accepted | [0023](0023-sheet-archive.md) |
| D14 | Sheet type geometry is versioned; sheets pin their version | 2026-11-05 | Accepted | [0023](0023-sheet-archive.md) |
| D15 | Cells are reserved at job creation, used on completion, unconfirmed when the outcome is unknown | 2026-11-05 | Accepted | [0023](0023-sheet-archive.md) |
| D16 | Lengths stored in hundredths of a millimetre | 2026-11-05 | Accepted | [0023](0023-sheet-archive.md) |
| D17 | Calibration stores the printer's deviation around the page centre; the hub applies the inverse | 2026-11-06 | Accepted | [0023](0023-sheet-archive.md) |
| D18 | IPP backend kind with an own client | 2026-11-06 | Accepted | [0020](0020-backend-kinds-ipp-page-printers.md) |
| D19 | Imported sheet types are never marked verified | 2026-11-05 | Accepted | [0023](0023-sheet-archive.md) |
| D21 | Minor and major releases come from `milestone/x.y.0` branches; main takes patch and non-releasing changes only | 2026-11-09 | Accepted | [0025](0025-milestone-branches-for-minor-and-major-releases.md) |
| D22 | The project is called Labelyard; names that users' data or clients depend on stay | 2026-11-11 | Accepted | [0026](0026-rename-to-labelyard.md) |
| D23 | The licence lists cover the Python environment and the web bundle the image ships, generated at build time; operating-system packages are covered by the image SBOM and their own copyright files | 2026-11-11 | Accepted | — |
| D24 | A print-scope API key may authenticate the Grocy label webhook as a literal `token=` URL parameter; admin keys are refused and the token is redacted from the hub's logs | 2026-11-14 | Accepted | [0027](0027-url-token-for-the-grocy-label-webhook.md) |
| V1 | Media type `labels` is settable on the test printer via `media-col` | 2026-11-06 | To verify | — |
| V2 | L4731REV has no vertical gap (pitch 10 mm) | 2026-11-05 | To verify | — |
| V3 | A QR does not scan reliably on 25.4 × 10 mm cells | 2026-11-05 | To verify | — |
| V4 | Corner radius of L4736REV (unknown, to measure) | 2026-11-05 | To verify | — |
