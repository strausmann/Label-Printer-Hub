# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The shipped sheet type seed file (Plan 1, Task 5)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.seed.sheet_seed import SEED_FILE, load_seed
from app.sheets.exchange import geometry_from_doc
from app.sheets.geometry import validate_geometry
from app.sheets.naming import KEY_PATTERN, PREFIX_PATTERN, derive_key, derive_prefix

HELD_BACK = {"7163", "8658", "L4730", "L4770", "7161", "3475"}
ALLOWED_NON_ASCII = {chr(c) for c in (0xD7, 0xB7, 0x2013, 0x2014)}  # x-sign, dot, dashes

# Expected prefix per key; L4731/L4736 drop the REV suffix, numeric codes get the vendor initial.
EXPECTED_PREFIX = {
    "avery-7160": "A7160", "avery-7162": "A7162", "avery-7164": "A7164",
    "avery-7165": "A7165", "avery-8651": "A8651", "avery-l4732": "L4732",
    "avery-zweckform-3474": "A3474", "avery-zweckform-3481": "A3481",
    "avery-zweckform-3669": "A3669", "avery-zweckform-4760": "A4760",
    "avery-zweckform-4761": "A4761", "avery-zweckform-4780": "A4780",
    "avery-zweckform-6021": "A6021", "avery-zweckform-l4731rev": "L4731",
    "avery-zweckform-l4736rev": "L4736", "endisch-6500040x": "E6500040X",
    "endisch-6500060x": "E6500060X", "herma-10001": "H10001", "herma-4097": "H4097",
    "herma-4098": "H4098", "herma-4103": "H4103", "herma-4283": "H4283",
    "herma-4293": "H4293", "herma-4606": "H4606", "herma-4607": "H4607",
    "herma-4614": "H4614", "herma-4625": "H4625", "avery-5159": "A5159",
    "avery-5160": "A5160", "avery-5161": "A5161", "avery-5162": "A5162",
    "avery-5163": "A5163", "avery-5164": "A5164", "avery-5167": "A5167",
    "avery-5195": "A5195", "avery-8195": "A8195",
}  # fmt: skip


def _by_key() -> dict[str, object]:
    _, docs = load_seed()
    return {d.type.key: d for d in docs}


def test_seed_has_36_valid_documents() -> None:
    revision, docs = load_seed()
    assert revision == 1
    assert len(docs) == 36
    keys = [d.type.key for d in docs]
    prefixes = [d.type.prefix for d in docs]
    assert len(set(keys)) == 36
    assert len(set(prefixes)) == 36
    for d in docs:
        assert KEY_PATTERN.match(d.type.key)
        assert PREFIX_PATTERN.match(d.type.prefix)
        assert d.type.verified is False
        assert d.version.version == 1
        assert d.exported_by_hub == "seed"
        validate_geometry(geometry_from_doc(d.version.geometry))
        assert d.type.key == derive_key(d.type.vendor or "", d.type.product_codes[0])
    assert {d.type.key: d.type.prefix for d in docs} == EXPECTED_PREFIX
    first = docs[0].type
    assert derive_prefix(first.vendor or "", first.product_codes[0]) == first.prefix


def test_seed_excludes_held_back_types() -> None:
    _, docs = load_seed()
    assert not {d.type.product_codes[0] for d in docs} & HELD_BACK


def test_seed_first_types_exact() -> None:
    by_key = _by_key()
    a = by_key["avery-zweckform-l4731rev"]
    g = a.version.geometry  # type: ignore[attr-defined]
    assert (g.label_w, g.label_h, g.cols, g.rows) == (25.4, 10.0, 7, 27)
    assert (g.pitch_x, g.pitch_y, g.margin_top, g.margin_left) == (27.9, 10.0, 13.5, 8.6)
    assert g.corner_radius == 1.5 and g.page_size == "A4" and g.shape == "rectangle"
    assert a.type.allow_qr is False  # type: ignore[attr-defined]
    assert a.type.source_name == "Labelplanet LP189/25; MR-Label MR111"  # type: ignore[attr-defined]
    b = by_key["avery-zweckform-l4736rev"]
    g = b.version.geometry  # type: ignore[attr-defined]
    assert (g.label_w, g.label_h, g.cols, g.rows) == (45.7, 21.2, 4, 12)
    assert (g.pitch_x, g.pitch_y, g.margin_top, g.margin_left) == (48.2, 21.2, 21.3, 9.85)
    assert g.corner_radius is None and g.page_size == "A4" and g.shape == "rectangle"
    assert b.type.allow_qr is True  # type: ignore[attr-defined]
    assert b.type.source_name == "Labelplanet LP48/45"  # type: ignore[attr-defined]
    assert b.type.notes.startswith("Vendor page not reachable;")  # type: ignore[attr-defined]


def _strings(node: object) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, list):
        return [s for item in node for s in _strings(item)]
    if isinstance(node, dict):
        return [s for k, v in node.items() for s in [k, *_strings(v)]]
    return []


def test_seed_is_english_and_private_clean() -> None:
    raw = json.loads(SEED_FILE.read_text(encoding="utf-8"))
    ipv4 = re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")
    for text in _strings(raw):
        stray = {ch for ch in text if not ch.isascii()} - ALLOWED_NON_ASCII
        assert not stray, f"non-English character(s) in {text[:40]!r}"
        assert not ipv4.search(text)
    for d in raw["types"]:
        assert d["type"]["source_url"].startswith("https://")


def test_seed_file_ships_in_package() -> None:
    assert SEED_FILE.is_file()
    assert Path(str(SEED_FILE)).name == "sheet_types.json"
