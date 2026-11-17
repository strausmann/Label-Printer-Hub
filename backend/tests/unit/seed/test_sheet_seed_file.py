# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The shipped sheet type seed file (Plan 1, Task 5)."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from app.seed.sheet_seed import SEED_FILE, load_seed, notice_code
from app.sheets.exchange import ExportDoc, geometry_from_doc
from app.sheets.geometry import geometry_hash, validate_geometry
from app.sheets.naming import (
    KEY_PATTERN,
    PREFIX_PATTERN,
    default_allow_qr,
    derive_key,
    derive_prefix,
)

HELD_BACK = {"7163", "8658", "L4730", "L4770", "7161", "3475"}
# x-sign, dot, dashes, plus-minus, minus sign, arrow (approved notes and change notes)
ALLOWED_NON_ASCII = {chr(c) for c in (0xD7, 0xB7, 0x2013, 0x2014, 0xB1, 0x2212, 0x2192)}
VERIFIED = {
    "avery-zweckform-6121",
    "avery-zweckform-3490",
    "avery-zweckform-l4737rev",
    "avery-zweckform-l4731rev",
}
REV1 = Path(__file__).parents[2] / "fixtures" / "seed" / "sheet_types_rev1.json"
L4737_HASH = "ca1dcfafb491a55240b24c343c483d96a462d6d7d10239b9c7e68c07dffce509"

# Expected prefix per key; L4731/L4736 drop the REV suffix, numeric codes get the vendor initial.
EXPECTED_PREFIX = {
    "avery-7160": "A7160", "avery-7162": "A7162", "avery-7164": "A7164",
    "avery-7165": "A7165", "avery-8651": "A8651", "avery-l4732": "L4732",
    "avery-zweckform-3474": "A3474", "avery-zweckform-3481": "A3481",
    "avery-zweckform-3669": "A3669", "avery-zweckform-4760": "A4760",
    "avery-zweckform-4761": "A4761", "avery-zweckform-4780": "A4780",
    "avery-zweckform-6021": "A6021", "avery-zweckform-l4731rev": "L4731",
    "avery-zweckform-6121": "A6121", "avery-zweckform-3490": "A3490",
    "avery-zweckform-l4737rev": "L4737",
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
    return {d.type.key: d for d in load_seed().docs}


def test_seed_revision_is_3() -> None:
    assert load_seed().revision == 3


def test_seed_has_39_valid_documents() -> None:
    seed = load_seed()
    docs = seed.docs
    assert seed.revision == 3
    assert len(docs) == 39
    keys = [d.type.key for d in docs]
    prefixes = [d.type.prefix for d in docs]
    assert len(set(keys)) == 39
    assert len(set(prefixes)) == 39
    for d in docs:
        assert KEY_PATTERN.match(d.type.key)
        assert PREFIX_PATTERN.match(d.type.prefix)
        assert d.type.verified is (d.type.key in VERIFIED)
        assert d.version.version == (2 if d.type.key == "avery-zweckform-l4731rev" else 1)
        assert d.exported_by_hub == "seed"
        validate_geometry(geometry_from_doc(d.version.geometry))
        assert d.type.key == derive_key(d.type.vendor or "", d.type.product_codes[0])
    assert {d.type.key: d.type.prefix for d in docs} == EXPECTED_PREFIX
    first = docs[0].type
    assert derive_prefix(first.vendor or "", first.product_codes[0]) == first.prefix


def test_seed_excludes_held_back_types() -> None:
    docs = load_seed().docs
    assert not {d.type.product_codes[0] for d in docs} & HELD_BACK


def test_seed_first_types_exact() -> None:
    by_key = _by_key()
    a = by_key["avery-zweckform-l4731rev"]
    g = a.version.geometry  # type: ignore[attr-defined]
    assert (g.label_w, g.label_h, g.cols, g.rows) == (25.4, 9.98, 7, 27)
    assert (g.pitch_x, g.pitch_y, g.margin_top, g.margin_left) == (27.9, 9.98, 12.54, 8.6)
    assert g.corner_radius == 1.5 and g.page_size == "A4" and g.shape == "rectangle"
    assert a.type.allow_qr is True  # type: ignore[attr-defined]
    assert a.type.source_name == "Labelplanet LP189/25; MR-Label MR111"  # type: ignore[attr-defined]
    b = by_key["avery-zweckform-l4736rev"]
    g = b.version.geometry  # type: ignore[attr-defined]
    assert (g.label_w, g.label_h, g.cols, g.rows) == (45.7, 21.2, 4, 12)
    assert (g.pitch_x, g.pitch_y, g.margin_top, g.margin_left) == (48.2, 21.2, 21.3, 9.85)
    assert g.corner_radius is None and g.page_size == "A4" and g.shape == "rectangle"
    assert b.type.allow_qr is True  # type: ignore[attr-defined]
    assert b.type.source_name == "Labelplanet LP48/45"  # type: ignore[attr-defined]
    assert b.type.notes.startswith("Vendor page not reachable;")  # type: ignore[attr-defined]


def test_seed_allow_qr_follows_the_creation_default() -> None:
    """Every seeded type starts with the QR switch the 10 mm rule gives it (OC-28, #330).

    The one exception is L4731REV: at 9.98 mm the rule says no, but a QR code prints and scans on
    it (the rule's own evidence), so the type keeps its switch on.
    """
    docs = load_seed().docs
    differ = {
        d.type.key
        for d in docs
        if d.type.allow_qr is not default_allow_qr(geometry_from_doc(d.version.geometry))
    }
    assert differ == {"avery-zweckform-l4731rev"}


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
        url = d["type"]["source_url"]
        assert url is None or url.startswith("https://")


def test_seed_file_ships_in_package() -> None:
    assert SEED_FILE.is_file()
    assert Path(str(SEED_FILE)).name == "sheet_types.json"


N6121 = (
    "Verified on real sheets 2026-11-15: HP Color LaserJet, tray 1, check print within "
    "+0.3 / \u00b10.2 mm. 5 columns of 38.1 mm with no horizontal gap (190.5 mm), rows 21.18 mm "
    "(275.34 mm); left edge 9.9 mm from the template, top 10.8 mm confirmed by the calibration "
    "print. Corner radius unknown. 65 labels per sheet; `-65` is the pack of 65 sheets."
)
N3490 = (
    "Verified on real sheets 2026-11-15: HP Color LaserJet, tray 1, check print within "
    "\u22120.33 to \u22120.50 mm across and \u00b10.3 mm down. Square-cut labels edge to edge, "
    "no side margin, top margin 4.5 mm. No usable margin: the sheet code is not printed in the "
    "margin (until #350)."
)
N4737 = (
    "Vendor template pages not reachable (HTTP 403). Size 63.5 x 29.6 mm and 27 per sheet "
    "confirmed by the Avery Zweckform catalogue 2022 "
    "(https://www.avery-zweckform.com/sites/default/files/2022-01/X93000-2022_Hauptkatalog_deutsch.pdf); "  # noqa: E501
    "grid, pitch and margins from Labelplanet LP27/63 only (same size and count, listed there "
    "without the L4737 code). Corner radius not stated anywhere; measure. No vertical gap "
    "(pitch 29.6 = label height). Labelplanet notes the height is sometimes manufactured slightly "
    "below 29.6 mm. Material: removable. Left margin measured 6.95 mm on two check prints "
    "(Labelplanet: 7.25); the die cut sits off-centre."
)


def _geometry(key: str):  # type: ignore[no-untyped-def]
    return _by_key()[key].version.geometry  # type: ignore[attr-defined]


def test_6121_entry() -> None:
    t = _by_key()["avery-zweckform-6121"]
    assert (t.type.key, t.type.prefix) == ("avery-zweckform-6121", "A6121")  # type: ignore[attr-defined]
    assert t.type.vendor == "Avery Zweckform"  # type: ignore[attr-defined]
    assert t.type.product_codes == ["6121", "6121-65"]  # type: ignore[attr-defined]
    g = t.version.geometry  # type: ignore[attr-defined]
    assert (g.label_w, g.label_h, g.cols, g.rows) == (38.1, 21.18, 5, 13)
    assert (g.pitch_x, g.pitch_y, g.margin_left, g.margin_top) == (38.1, 21.18, 9.9, 10.8)
    assert g.corner_radius is None and g.page_size == "A4" and g.shape == "rectangle"
    assert t.type.verified and t.type.allow_qr and t.version.version == 1  # type: ignore[attr-defined]
    assert t.type.source_url is None  # type: ignore[attr-defined]
    assert t.type.source_name == "Avery Zweckform Word template 6121"  # type: ignore[attr-defined]
    assert t.type.description == "Universal labels"  # type: ignore[attr-defined]
    assert t.type.notes == N6121  # type: ignore[attr-defined]


def test_3490_entry() -> None:
    t = _by_key()["avery-zweckform-3490"]
    assert t.type.prefix == "A3490" and t.type.vendor == "Avery Zweckform"  # type: ignore[attr-defined]
    assert t.type.product_codes == ["3490"]  # type: ignore[attr-defined]
    assert t.type.description == "Universal labels, 70 x 36 mm, square cut"  # type: ignore[attr-defined]
    assert t.type.source_name == "Labelplanet LP24/70SS; glabels-qt Zweckform 3490"  # type: ignore[attr-defined]
    assert t.type.source_url == (  # type: ignore[attr-defined]
        "https://www.labelplanet.co.uk/label-templates-for-square-cut-rectangle-labels/"
        "label-templates-24-per-sheet-lp24-70ss/"
    )
    g = t.version.geometry  # type: ignore[attr-defined]
    assert (g.label_w, g.label_h, g.cols, g.rows) == (70, 36, 3, 8)
    assert (g.pitch_x, g.pitch_y, g.margin_left, g.margin_top) == (70, 36, 0, 4.5)
    assert g.corner_radius is None and g.page_size == "A4" and g.shape == "rectangle"
    assert t.type.verified and t.type.allow_qr and t.version.version == 1  # type: ignore[attr-defined]
    assert t.type.notes == N3490  # type: ignore[attr-defined]


def test_l4737rev_entry() -> None:
    t = _by_key()["avery-zweckform-l4737rev"]
    assert (t.type.prefix, t.type.vendor) == ("L4737", "Avery Zweckform")  # type: ignore[attr-defined]
    assert t.type.product_codes == [  # type: ignore[attr-defined]
        "L4737REV-25", "L4737REV-10", "L4737REV-100", "L4737",
    ]  # fmt: skip
    assert t.type.description == "Universal labels, removable"  # type: ignore[attr-defined]
    assert t.type.source_name == (  # type: ignore[attr-defined]
        "Labelplanet LP27/63; Avery Zweckform catalogue 2022 (size only)"
    )
    assert t.type.source_url == (  # type: ignore[attr-defined]
        "https://www.labelplanet.co.uk/label-templates-for-rounded-rectangle-labels/"
        "label-templates-27-per-sheet-lp27-63/"
    )
    assert t.type.notes == N4737  # type: ignore[attr-defined]
    g = t.version.geometry  # type: ignore[attr-defined]
    assert (g.label_w, g.label_h, g.cols, g.rows) == (63.5, 29.6, 3, 9)
    assert (g.pitch_x, g.pitch_y, g.margin_left, g.margin_top) == (66.0, 29.6, 6.95, 15.3)
    assert g.corner_radius is None and g.page_size == "A4" and g.shape == "rectangle"
    assert t.type.verified and t.type.allow_qr and t.version.version == 1  # type: ignore[attr-defined]
    assert geometry_hash(geometry_from_doc(g)) == L4737_HASH


def test_new_geometries_are_valid() -> None:
    hints = {key: validate_geometry(geometry_from_doc(_geometry(key))) for key in sorted(VERIFIED)}
    assert hints == {
        "avery-zweckform-3490": [],
        "avery-zweckform-6121": [],
        "avery-zweckform-l4731rev": ["margins_asymmetric_y"],
        "avery-zweckform-l4737rev": ["margins_asymmetric_x"],
    }


def test_adopt_map_names_6121_3490_and_l4737rev() -> None:
    adopt = load_seed().adopt
    assert set(adopt) == {
        "avery-zweckform-6121",
        "avery-zweckform-3490",
        "avery-zweckform-l4737rev",
    }
    for a in adopt.values():
        assert a.revision == 2
        assert a.change_note == "Verified geometry shipped with Labelyard 1.7.0"


def test_adopt_keys_are_seed_keys() -> None:
    seed = load_seed()
    keys = {d.type.key for d in seed.docs}
    assert set(seed.adopt) <= keys and set(seed.corrections) <= keys


def test_l4731rev_entry_is_corrected() -> None:
    t = _by_key()["avery-zweckform-l4731rev"]
    g = t.version.geometry  # type: ignore[attr-defined]
    assert (g.label_w, g.label_h, g.cols, g.rows) == (25.4, 9.98, 7, 27)
    assert (g.pitch_x, g.pitch_y, g.margin_top, g.margin_left) == (27.9, 9.98, 12.54, 8.6)
    assert g.corner_radius == 1.5 and g.page_size == "A4" and g.shape == "rectangle"
    assert t.version.version == 2  # type: ignore[attr-defined]
    assert t.type.verified is True and t.type.allow_qr is True  # type: ignore[attr-defined]
    old = next(d for d in _rev1_docs() if d.type.key == "avery-zweckform-l4731rev").type.notes
    notes = t.type.notes  # type: ignore[attr-defined]
    assert notes.startswith("Verified on real sheets 2026-11-15: HP Color LaserJet, tray 1")
    assert "corrected to top 12.54 mm and 9.98 mm rows." in notes
    assert notes.endswith(old)
    assert validate_geometry(geometry_from_doc(g)) == ["margins_asymmetric_y"]
    assert geometry_hash(geometry_from_doc(g)) == (
        "15db36b9fbce8bb83f06adb92043c9d33ba0399d999f5266f1e08ea5abf5075b"
    )


def _rev1_docs() -> list[ExportDoc]:
    return load_seed(REV1).docs


def test_correction_names_l4731rev() -> None:
    corr = load_seed().corrections
    assert set(corr) == {"avery-zweckform-l4731rev"}
    c = corr["avery-zweckform-l4731rev"]
    old = next(d for d in _rev1_docs() if d.type.key == "avery-zweckform-l4731rev")
    assert c.revision == 2
    assert c.change_note == (
        "Verified geometry shipped with Labelyard 1.7.0 "
        "(top margin 13.5 \u2192 12.54 mm, row pitch 10.0 \u2192 9.98 mm)"
    )
    assert c.previous_geometry_hash == geometry_hash(geometry_from_doc(old.version.geometry))
    assert c.previous_notes_sha256 == hashlib.sha256(old.type.notes.encode()).hexdigest()


def test_notice_code_drops_the_pack_size() -> None:
    assert notice_code(["L4731REV-25", "L4731REV-10", "L4731"]) == "L4731REV"
    assert notice_code(["6121", "6121-65"]) == "6121"
    assert notice_code(["3490"]) == "3490"
    assert notice_code(["L4737REV-25"]) == "L4737REV"
    assert notice_code(["6121-X"]) == "6121-X"
    assert notice_code([]) == ""
