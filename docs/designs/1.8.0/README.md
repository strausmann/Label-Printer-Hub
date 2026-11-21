# Design mockups for release 1.8.0

Static, self-contained HTML pages (inline CSS, fonts and JS, no network) that show what the
[1.8.0 design](../../superpowers/specs/2026-11-21-milestone-1-8-0-design.md) asks for. They use the
app's real tokens, light and dark. All names, printers and addresses are invented; sheet types are
Avery Zweckform ones. Zone positions and correction values are demo values, not measurements.

Open a page directly, or add `?theme=dark`, `?view=<name>`. M6 was dropped from the milestone.

| Mockup | Spec | Page | Views |
|---|---|---|---|
| M1 Preprinted areas | 5, 11 | `m01-preprinted-areas.html` | default, editor (keyboard) |
| M2 Sheet code section | 5, 11 | `m02-sheet-code-section.html` | default |
| M3 Check pages (paper) | 7.3, 11 | `m03-check-pages.html` | A4, light only |
| M4 Catalog tab | 6, 11 | `m04-catalog-tab.html` | default, empty, search (keyboard) |
| M5 Installed types | 6, 11 | `m05-installed-types.html` | default, remove (keyboard) |
| M7 Calibration history | 7.5, 11 | `m07-calibration-history.html` | default, restore (keyboard) |
| M8 Calibration readings | 7.4, 11 | `m08-calibration-readings.html` | default, entry (keyboard) |
| M9 Probe print (paper) | 7.3, 5.5, 11 | `m09-probe-print.html` | A4 pages, light only |
| M10 Printer not wired | 9.3, 11 | `m10-printer-not-wired.html` | default |
| M11 Public web URL | 9.4, 11 | `m11-integrations-web-url.html` | default, field (keyboard) |
| M12 Type log | 7.6, 11 | `m12-type-log.html` | default, note (keyboard) |
| M13 Cell panel | 8.1, 11 | `m13-cell-panel.html` | default, old cell |

Screenshots are in `png/`: `<page>[-<view>]-<1280|390>-<light|dark>.png`, plus
`-390x500-light.png` for the keyboard-open views (section 12) and `-a4-light.png` for the paper pages.

## Rebuild

```
cd frontend && pnpm install
node ../docs/designs/1.8.0/src/build.mjs          # pages
node ../docs/designs/1.8.0/src/shoot.mjs          # screenshots (Playwright from frontend/)
pip install segno && python3 docs/designs/1.8.0/src/gen_qr.py   # QR data (already committed)
```

## Decisions I made (spec left them open)

- Sheet-code and cell QR codes are real LYC1 codes (alphanumeric mode, 5-M page, 1-M cell) generated with segno.
- Check passes use disjoint, non-touching crossing sets (K1 5, K2 4, K3 3 crossings).
- The keyboard is simulated with a 390x500 viewport; dialogs align top there and keep a sticky footer.
- Pages on narrow screens turn tables into card lists.
- M11 shows a refused address (with a user name) and an empty one next to a saved one.
