<!--
SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
SPDX-License-Identifier: AGPL-3.0-or-later
-->

# reportlab PDF output: spike S1

Date: 2026-11-05. Spike for the sheet archive PDF writer (Plan 2, Task 10).
Tested with reportlab 5.1.0, Pillow 13.0.0, CPython 3.12, in a throw-away venv. The scratch
scripts are not committed. Poppler `pdfimages` was used to cross-check the image XObject.

## Summary

| Question | Answer |
|---|---|
| (a) Mode `"1"` image stays 1 bit? | **No.** `drawImage` and `drawInlineImage` both expand it to 8-bit `/DeviceRGB`. Use a small `PDFImageXObject` subclass (below) to get a real `/BitsPerComponent 1 /DeviceGray` image. |
| (b) Content stream readable with `pageCompression=0`? | Yes. Operators sit at the end of their own line and match a line-anchored regex. |
| (c) `setFillGray`/`setStrokeGray` avoid `rg`/`k`? | Yes, including text. The control (`setFillColorRGB`) does emit `rg`. |
| (d) DejaVu Sans lookup | `TTFont` resolves a bare `DejaVuSans.ttf` through `rl_config.TTFSearchPath`; do not rely on it. Resolve the path explicitly and fail loudly. |
| (e) `invariant=True` byte-identical? | Yes. Two renders one second apart differ without it and are identical with it. |
| (f) Version and transitive deps | reportlab 5.1.0 is current on PyPI. Requires `pillow>=9.0.0` and `charset-normalizer` (MIT). |

## (a) Image preparation

Input: a 64x32 PIL image, mode `"1"`.

| Call | Resulting image XObject |
|---|---|
| `drawImage(ImageReader(im1))`, also with `mask="auto"` | `/BitsPerComponent 8 /ColorSpace /DeviceRGB`, Flate+ASCII85 |
| `drawInlineImage(im1)` | inline image (`BI ... EI`), no XObject dictionary to assert on |
| `drawImage(ImageReader(im1.convert("L")))` | `/BitsPerComponent 8 /ColorSpace /DeviceGray`, no resampling, `Width 64 /Height 32` kept |

Why: `PDFImageXObject.loadImageFromSRC` always calls `ImageReader.getRGBData()` and hard-codes
`bitsPerComponent = 8`. There is no 1 bit path in the public API, and no `/ImageMask` is
produced either.

Consequences for Task 10:

* `drawImage` with `.convert("L")` is the simple option. It is DeviceGray, never RGB, never
  resampled (the drawing matrix scales it, the pixel grid is untouched). It costs 8x the raw
  size before Flate; for a bilevel sheet this compresses to almost nothing.
* A true 1 bit image needs the helper below. Chosen for the writer if a test must assert
  `/BitsPerComponent 1`. Verified: `pdfimages -list` reports `gray 1 comp, 1 bpc`, and the
  extracted pixels are byte-identical to `im.tobytes()`, including for a width that is not a
  multiple of 8 (13 px, rows padded to whole bytes).

```python
class BilevelXObject(PDFImageXObject):
    def __init__(self, name, im):           # im.mode must be "1"
        super().__init__(name, None)         # source=None: no PIL conversion
        self.width, self.height = im.size
        self.colorSpace, self.bitsPerComponent, self.mask = "DeviceGray", 1, None
        self.streamContent = zlib.compress(im.tobytes())   # packed 1 bpp, 1 = white
        self._filters = ("FlateDecode",)

def draw_bilevel(c, im, x, y, w, h):
    name = hashlib.md5(im.tobytes() + repr(im.size).encode()).hexdigest()
    reg = c._doc.getXObjectName(name)
    if not c._doc.idToObject.get(reg):
        obj = BilevelXObject(name, im); obj.name = name
        c._setXObjects(obj); c._doc.Reference(obj, reg); c._doc.addForm(name, obj)
    c.saveState(); c.translate(x, y); c.scale(w, h)
    c._code.append("/%s Do" % reg); c.restoreState()
    c._formsinuse.append(name); c._currentPageHasImages = 1
```

This mirrors the body of `Canvas.drawImage` and touches underscore members
(`_doc`, `_code`, `_formsinuse`, `_setXObjects`). Pin reportlab to a minor range and keep a
test that asserts `/BitsPerComponent 1`, so an upgrade that breaks it is loud. Emitted
dictionary: `/BitsPerComponent 1 /ColorSpace /DeviceGray /Filter [ /FlateDecode ] /Width 13 /Height 5`.

`/ImageMask` was not needed and was not tried further; a 1 bit DeviceGray image with a
black ink pixel value of 0 is the right shape for "print exactly these dots".

## (b) Readable content stream

With `Canvas(..., pageCompression=0)` the page stream is plain text. Observed (comments added):

```
1 0 0 1 0 0 cm  BT /F1 12 Tf 14.4 TL ET     % reportlab preamble, two ops on one line
0 g                                         % setFillGray(0)
.5 G                                        % setStrokeGray(0.5)
.5 w
n 10 10 m 100 10 l S                        % line
n 10 20 50 30 re S                          % rect
BT 1 0 0 1 10 180 Tm /F2+0 9 Tf 10.8 TL (Hello \001 \002 ...) Tj T* ET
q
64 0 0 32 20 100 cm                         % image matrix: width 0 0 height x y
/FormXob.<digest> Do
Q
```

Tests can match with `(?m)\s(rg|RG|k|K)\s*$` (must be absent) and read the image matrix with
`([\d. -]+) cm\n/FormXob`. Traps:

* The preamble line packs `cm` and `Tf` onto one line; match operators anywhere, not only
  at line start, and do not assert on the preamble.
* Numbers are trimmed (`.5`, not `0.5`).
* Text is subset-encoded (`\001`, `\002`), not the literal string. Assert text content via the
  `/ToUnicode` CMap or by rendering, not by grepping for the string.
* The `/ProcSet` list always advertises `/ImageC`; assert on the colour spaces actually used.
  In a document with only gray operators, a bilevel image and an embedded TrueType font, the
  bytes `DeviceRGB` and `DeviceCMYK` do not occur anywhere; `DeviceGray` does.
* Image XObjects use ASCII85+Flate unless `rl_config.useA85 = 0`; the bilevel helper above
  writes Flate only. Decode before asserting on pixels.

## (c) Gray only

`setFillGray(0.2)`, `setStrokeGray(0.8)` and then `drawString` emit `.2 g` / `.8 G` and nothing
else; text uses the fill colour. Control: `setFillColorRGB(1, 0, 0)` emits `1 0 0 rg`, so the
regex genuinely detects what it claims to. Do not rely on the canvas default colour; call `setFillGray(0)` / `setStrokeGray(0)` explicitly.

## (d) DejaVu Sans

* Production image (`backend/Dockerfile`, runtime stage `python:3.12-slim-bookworm`):
  `fonts-dejavu-core` is installed for the label renderer. It provides
  `/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf`.
* CI: every job in `.github/workflows/ci.yml` runs on `ubuntu-24.04` and none installs fonts.
  The spike host (also Ubuntu 24.04) has `fonts-dejavu-core 2.37-8` and it is found there,
  but a hosted-runner image can change. Not verified against the runner image.
* reportlab: `TTFont("X", "DejaVuSans.ttf")` succeeded here because `/usr/share/fonts/truetype`
  is in `rl_config.TTFSearchPath`. A missing file raises `TTFError: Can't open file "..."`,
  which names the file but not the cause or the remedy.
* The font is embedded as a subset (`/BaseFont /AAAAAA+DejaVuSans`, `/FontFile2`), so the
  output does not depend on the viewer having it.

Recommendation: one function, `resolve_font_path()`, used by the writer:

1. `PRINTHUB_PDF_FONT` environment variable (absolute path), if set.
2. Else `/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf`.
3. If the file does not exist: raise a dedicated error naming both, for example "DejaVu Sans
   not found at <path>; install fonts-dejavu-core or set PRINTHUB_PDF_FONT".

Do not use the bare-name search: it makes the result depend on every directory in
`TTFSearchPath` including `~/fonts` and the working directory. Register the font once
(`pdfmetrics.registerFont`), guarded so repeat calls are harmless. CI: add
`sudo apt-get install -y fonts-dejavu-core` to the backend job (cheap, idempotent) rather
than relying on the runner image. Optionally bundle the font file in the repo instead; DejaVu
fonts are free to redistribute (Bitstream Vera licence), but the policy question of shipping a
binary is left to the controller.

## (e) Determinism

`Canvas(..., invariant=True)` (equivalently `invariant=1`):

| | Result |
|---|---|
| default, two renders one second apart | **different** bytes (CreationDate/ModDate/ID drift) |
| `invariant=1`, two renders 1.1 s apart | **identical** bytes |
| Info dictionary | `/CreationDate (D:20000101000000+00'00') /ModDate (same) /Creator (anonymous) /Producer (ReportLab PDF Library - (opensource))` |
| trailer `/ID` | `[<digest><digest>]`, digest derived from content |

The `/ID` is a hash of the content, so it is stable for identical input and changes with it.
Identical input also needs identical Python/reportlab/Pillow versions; the font subset prefix
(`AAAAAA+`) is deterministic.

## (f) Version, dependencies, licence

* Current: **reportlab 5.1.0** (`pip index versions reportlab`, 2026-11-05).
* Runtime requires: `pillow>=9.0.0`, `charset-normalizer`. Extras (`accel`, `renderpm`,
  `pycairo`, `bidi`, `shaping`) are not needed. Pillow is already a backend dependency.
* Correction to the brief: `charset-normalizer` is already required by 4.4.3 (and 4.4.4), not
  only from 4.4.4. 4.2.5 still required `chardet`. Irrelevant for 5.1.0.
* Licence check against `licence-policy.yml` (present on this branch):
  * `charset-normalizer` 3.5.2: MIT, in `allow-licenses`.
  * `reportlab` 5.1.0: metadata says `License: BSD license (see license.txt ...)` with the
    classifier `License :: OSI Approved :: BSD License`; the shipped `LICENSE` is the BSD
    3-clause text. `BSD-3-Clause` is allowed, but the bare classifier is not an SPDX id, so the
    licence gate will likely flag it. **Task 10 must add an `x-licence-exceptions` entry** for
    `pkg:pypi/reportlab` (`BSD-3-Clause`, reason: bare BSD classifier, licence file is the
    3-clause text), the same pattern as `jinja2` and `pyusb`. It is compatible with
    AGPL-3.0-or-later. Not run through the real gate in this spike.
* `THIRD_PARTY_NOTICES.md` likely needs a reportlab line (Task 10).

## Decisions for Task 10

1. Colour: only `setFillGray` / `setStrokeGray`, set explicitly before drawing.
2. Images: bilevel via the `BilevelXObject` helper (true 1 bit), falling back to
   `convert("L")` + `drawImage` if the helper proves fragile.
3. Output: `Canvas(buf, pageCompression=0, invariant=True)` for tests; production may keep
   compression, but the determinism test needs `invariant=True` either way.
4. Font: `resolve_font_path()` with env override and explicit error; install
   `fonts-dejavu-core` in CI.
5. Add the licence exception and pin `reportlab>=5.1,<5.2` (the helper uses private members).
