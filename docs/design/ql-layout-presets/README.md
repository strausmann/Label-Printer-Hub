# QL 62 mm across-width layout presets (reference for #258)

These were printed on a real QL-820NWB with 62 mm DK endless tape on 2026-11-09. The text runs across the tape and the label length follows the content. The maintainer chose **compact** as the preferred layout and asked for it to become a saved layout with a preview. The other two stay available as templates.

| Preset | Preview | QR code | QR quiet zone along the feed | Layout margin along the feed | Feed margin sent | Content length |
|---|---|---|---|---|---|---|
| Compact (preferred) | ![compact](ql62-across-compact.png) | 18.8 mm (6 px modules, version 3) | 2 modules | 0 mm | 0 dots | 16.8 mm |
| Small QR | ![small QR](ql62-across-small-qr.png) | 18.8 mm | 4 modules | 0.5 mm | 12 dots | 19.8 mm |
| Standard | ![standard](ql62-across-standard.png) | 21.9 mm (42 % of width) | 4 modules | 2 mm | 35 dots (brother_ql default) | 26.0 mm |

## Common to all three

- The width across the tape is exactly `dots_printable[0]` = 696 px at 300 dpi, so `brother_ql` never resizes the image.
- The QR code is on the left. Every module is a whole number of device pixels. The quiet zone across the width is 4 modules.
- The text block sits to the right of the QR code:
  - code (asset tag) in IBM Plex Mono Bold, largest;
  - title in Atkinson Hyperlegible Next Bold;
  - model in Atkinson Hyperlegible Next Regular;
  - serial in IBM Plex Mono.
- Text is rendered in greyscale and then thresholded at about 55 % ink.
- Within a preset the QR size is fixed per tape width. More text makes the label longer and never makes the QR smaller (maintainer decision).

## Open points for the implementation

- **Resolved (2026-11-09, four prints in a row):** the QL-820NWB keeps about **3 mm of feed at each end** whatever feed margin is sent (35, 12 or 0 dots). The labels only got shorter by the layout margin removed in the image. Implementation: keep the brother_ql default feed margin, since sending less has no effect. Minimise only the layout margin and the quiet zone along the feed. Minimum label length = content + about 2 × 3 mm.
- Scan reliability of the 2-module quiet zone. ISO/IEC 18004 asks for 4 modules, while most phone scanners accept 2.
- Make the orientation explicit (`across` or `along`) instead of the 1.4.1 size heuristic. See the #258 comments.

`render_reference.py` regenerates the compact preview (`--send tcp://<host>:9100` prints it).
