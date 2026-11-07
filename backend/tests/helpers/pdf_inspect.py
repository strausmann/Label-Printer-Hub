"""Read back what ``write_pdf`` produced, without a PDF library.

These helpers are regular expressions and a tiny content-stream interpreter over the output of
``write_pdf(..., compress=False)``. They understand exactly the subset reportlab emits for this
project (one page, plain-text page content, an uncompressed ``/ToUnicode`` CMap per font
subset) and nothing more. On anything else they fail loudly rather than guess.

The preamble
------------
reportlab starts every page stream with one fixed line::

    1 0 0 1 0 0 cm  BT /F1 12 Tf 14.4 TL ET

It combines ``cm`` and ``Tf`` on a single line and is not content the writer drew. Every helper
here removes exactly that line before looking at the stream, so "the first ``cm``" means the
first ``cm`` *after the preamble*. If a reportlab upgrade changes the preamble, the removal no
longer matches, the identity ``cm`` stays in front, and the tests that depend on "first" fail.
"""

from __future__ import annotations

import re
from typing import Any

#: Colour-setting operators (PDF 32000-1, table 74). A gray-only page contains none of them;
#: ``g`` and ``G`` are the gray operators and are deliberately absent.
COLOUR_OPERATORS = frozenset({"rg", "RG", "k", "K", "sc", "SC", "scn", "SCN", "cs", "CS"})

_PREAMBLE = re.compile(rb"\A\s*1 0 0 1 0 0 cm\s+BT /F\d+ [\d.]+ Tf [\d.]+ TL ET[ \t]*\r?\n")
_STRING = rb"\((?:\\.|[^\\()])*\)"
_TOKEN = re.compile(
    rb"(?P<str>" + _STRING + rb")"
    rb"|(?P<hex><[0-9A-Fa-f\s]*>)"
    rb"|(?P<name>/[^\s/\[\]()<>]+)"
    rb"|(?P<num>[-+]?(?:\d+\.?\d*|\.\d+))"
    rb"|(?P<arr>[\[\]])"
    rb"|(?P<op>[A-Za-z][A-Za-z0-9*]*|['\"*])",
    re.DOTALL,
)


def _object_body(pdf: bytes, number: int) -> bytes:
    match = re.search(rb"(?:\A|\n)%d 0 obj\b(.*?)\bendobj" % number, pdf, re.DOTALL)
    if match is None:
        raise AssertionError(f"object {number} not found")
    return match.group(1)


def _stream_of(pdf: bytes, number: int) -> bytes:
    body = _object_body(pdf, number)
    match = re.search(rb"stream\r?\n(.*?)\r?\n?endstream", body, re.DOTALL)
    if match is None:
        raise AssertionError(f"object {number} has no stream")
    return match.group(1)


def _page_content(pdf: bytes) -> bytes:
    match = re.search(rb"/Contents (\d+) 0 R", pdf)
    if match is None:
        raise AssertionError("no /Contents in the PDF")
    content = _stream_of(pdf, int(match.group(1)))
    if b"FlateDecode" in _object_body(pdf, int(match.group(1))).split(b"stream", 1)[0]:
        raise AssertionError("page content is compressed; render with compress=False")
    return _PREAMBLE.sub(b"", content, count=1)


def _parse(content: bytes) -> list[tuple[str, list[Any]]]:
    """Split a content stream into ``(operator, operands)``; strings stay raw bytes."""
    result: list[tuple[str, list[Any]]] = []
    operands: list[Any] = []
    for m in _TOKEN.finditer(content):
        kind = m.lastgroup
        raw = m.group()
        if kind == "num":
            operands.append(float(raw))
        elif kind == "str":
            operands.append(raw)
        elif kind == "name":
            operands.append(raw.decode("latin-1"))
        elif kind in ("hex", "arr"):
            operands.append(raw)
        else:
            result.append((raw.decode("latin-1"), operands))
            operands = []
    return result


def operations(pdf: bytes) -> list[tuple[str, list[float]]]:
    """Every content operator with its numeric operands (strings, names and brackets dropped)."""
    return [
        (op, [a for a in args if isinstance(a, float)]) for op, args in _parse(_page_content(pdf))
    ]


def media_box(pdf: bytes) -> tuple[float, ...]:
    match = re.search(rb"/MediaBox \[\s*([-\d.\s]+?)\s*\]", pdf)
    if match is None:
        raise AssertionError("no /MediaBox in the PDF")
    return tuple(float(v) for v in match.group(1).split())


def operators(pdf: bytes) -> list[str]:
    """Every content operator of the page, in order, text and inline strings excluded."""
    return [op for op, _ in _parse(_page_content(pdf))]


def colour_operators(pdf: bytes) -> set[str]:
    """The colour-setting operators the page uses (empty for a gray-only page)."""
    return set(operators(pdf)) & COLOUR_OPERATORS


def cm_matrices(pdf: bytes) -> list[tuple[float, ...]]:
    """Every ``cm`` matrix after the preamble, in stream order."""
    return [tuple(args) for op, args in _parse(_page_content(pdf)) if op == "cm"]


def images(pdf: bytes) -> list[dict[str, Any]]:
    """The image XObject dictionaries: BitsPerComponent, ColorSpace, ImageMask, Width, Height."""
    found: list[dict[str, Any]] = []
    for m in re.finditer(rb"<<((?:(?!>>).)*?/Subtype /Image(?:(?!>>).)*?)>>", pdf, re.DOTALL):
        d = m.group(1)

        def num(key: bytes, d: bytes = d) -> int | None:
            hit = re.search(rb"/" + key + rb" (\d+)", d)
            return int(hit.group(1)) if hit else None

        colour = re.search(rb"/ColorSpace (/\w+)", d)
        found.append(
            {
                "BitsPerComponent": num(b"BitsPerComponent"),
                "ColorSpace": colour.group(1).decode() if colour else None,
                "ImageMask": re.search(rb"/ImageMask true", d) is not None,
                "Width": num(b"Width"),
                "Height": num(b"Height"),
            }
        )
    return found


def text_positions(pdf: bytes) -> list[tuple[float, float]]:
    """Origin of every shown string in page coordinates (after the CTM), one per ``Tj``.

    Only the start of the text line is reported; the advance of an earlier ``Tj`` in the same
    ``BT`` block is not tracked (reportlab's ``drawString`` opens one block per string).
    """
    ident = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

    def mul(m: tuple[float, ...], n: tuple[float, ...]) -> tuple[float, ...]:
        """``m`` applied first, then ``n`` (row-vector convention of PDF)."""
        return (
            m[0] * n[0] + m[1] * n[2],
            m[0] * n[1] + m[1] * n[3],
            m[2] * n[0] + m[3] * n[2],
            m[2] * n[1] + m[3] * n[3],
            m[4] * n[0] + m[5] * n[2] + n[4],
            m[4] * n[1] + m[5] * n[3] + n[5],
        )

    ctm: tuple[float, ...] = ident
    stack: list[tuple[float, ...]] = []
    line: tuple[float, ...] = ident
    out: list[tuple[float, float]] = []
    for op, args in _parse(_page_content(pdf)):
        if op == "q":
            stack.append(ctm)
        elif op == "Q":
            ctm = stack.pop()
        elif op == "cm":
            ctm = mul(tuple(args), ctm)
        elif op == "BT":
            line = ident
        elif op == "Tm":
            line = tuple(args)
        elif op == "Td":
            line = mul((1.0, 0.0, 0.0, 1.0, args[0], args[1]), line)
        elif op in ("Tj", "TJ"):
            page = mul(line, ctm)
            out.append((page[4], page[5]))
    return out


def texts(pdf: bytes) -> list[str]:
    """The text of every ``Tj``, decoded through the font subset's ``/ToUnicode`` CMap.

    The content stream holds subset codes, not the string. Decoding through the CMap is the
    reverse of what a viewer does for copy and paste, so a match proves the writer encoded
    exactly this text and did not interpret or strip any of it.
    """
    fonts = {name.decode(): int(ref) for name, ref in re.findall(rb"/(F\d+\+\d+) (\d+) 0 R", pdf)}
    cmaps: dict[str, dict[int, str]] = {}
    current = ""
    result: list[str] = []
    for op, args in _parse(_page_content(pdf)):
        if op == "Tf":
            current = args[0].lstrip("/")
        elif op == "Tj":
            if current not in cmaps:
                cmaps[current] = _to_unicode(pdf, fonts[current])
            result.append("".join(cmaps[current].get(c, "\ufffd") for c in _unescape(args[0])))
    return result


def _to_unicode(pdf: bytes, font_object: int) -> dict[int, str]:
    ref = re.search(rb"/ToUnicode (\d+) 0 R", _object_body(pdf, font_object))
    if ref is None:
        raise AssertionError(f"font object {font_object} has no /ToUnicode")
    cmap = _stream_of(pdf, int(ref.group(1)))
    mapping: dict[int, str] = {}
    # Only the bfchar blocks: the codespacerange line has the same <xx> <yy> shape.
    for block in re.findall(rb"beginbfchar(.*?)endbfchar", cmap, re.DOTALL):
        for code, uni in re.findall(rb"<([0-9A-Fa-f]{2})>\s*<([0-9A-Fa-f]+)>", block):
            try:
                mapping[int(code, 16)] = bytes.fromhex(uni.decode()).decode("utf-16-be")
            except ValueError:
                # reportlab writes a character outside the BMP as an odd-length <1F600>, which
                # is not valid UTF-16BE; leave the code unmapped (texts() shows U+FFFD).
                continue
    return mapping


def _unescape(literal: bytes) -> bytes:
    """Decode a PDF literal string (``( ... )``) to its bytes."""
    body = literal[1:-1]
    out = bytearray()
    i = 0
    simple = {ord("n"): 10, ord("r"): 13, ord("t"): 9, ord("b"): 8, ord("f"): 12}
    while i < len(body):
        ch = body[i]
        if ch != 0x5C:
            out.append(ch)
            i += 1
            continue
        i += 1
        nxt = body[i]
        if 0x30 <= nxt <= 0x37:
            digits = body[i : i + 3]
            octal = re.match(rb"[0-7]{1,3}", digits)
            assert octal is not None
            out.append(int(octal.group(), 8) & 0xFF)
            i += len(octal.group())
        else:
            out.append(simple.get(nxt, nxt))
            i += 1
    return bytes(out)
