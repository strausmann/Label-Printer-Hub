# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""IPP codec (RFC 8010) — fixtures, round trips and hostile input.

The ``.bin`` fixtures are assembled by hand in ``fixtures/assemble.py`` from the
RFC field layout and never produced by the codec under test.
"""

from __future__ import annotations

import contextlib
import random
from pathlib import Path

import pytest
from app.printer_backends.ipp import codec
from app.printer_backends.ipp.codec import (
    MAX_DEPTH,
    MAX_VALUES,
    OPERATIONS,
    STATUS_NAMES,
    Attr,
    Collection,
    Group,
    Message,
    OutOfBand,
    Range,
    Resolution,
    Tag,
    Unknown,
    decode,
    encode,
)
from app.printer_backends.ipp.errors import IppDecodeError, IppEncodeError

from tests.unit.printer_backends.ipp.fixtures import assemble as wire

FIXTURES = Path(__file__).parent / "fixtures"
URI = "ipp://printer.example.invalid/ipp/print"


def _fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _op_group(*extra: Attr) -> Group:
    return Group(
        Tag.OPERATION,
        [
            Attr("attributes-charset", Tag.CHARSET, ["utf-8"]),
            Attr("attributes-natural-language", Tag.LANGUAGE, ["en"]),
            Attr("printer-uri", Tag.URI, [URI]),
            *extra,
        ],
    )


def _minimal(*attrs: bytes, group: int = 0x01) -> bytes:
    """Header + one group holding the given raw attributes + end tag."""
    return wire.HEADER_GPA + bytes([group]) + b"".join(attrs) + wire.END_OF_ATTRIBUTES


# --------------------------------------------------------------------------- fixtures


def test_roundtrip_get_printer_attributes_request() -> None:
    msg = Message(
        version=(1, 1),
        code=OPERATIONS["Get-Printer-Attributes"],
        request_id=1,
        groups=[
            _op_group(Attr("requested-attributes", Tag.KEYWORD, ["printer-state", "marker-levels"]))
        ],
    )
    expected = _fixture("gpa_request.bin")

    assert encode(msg) == expected
    decoded, document = decode(expected)
    assert decoded == msg
    assert document == b""


def test_decode_response_types() -> None:
    msg, document = decode(_fixture("gpa_response.bin"))

    assert document == b""
    assert msg.version == (1, 1)
    assert msg.code == 0x0000
    assert msg.request_id == 1
    assert [g.tag for g in msg.groups] == [Tag.OPERATION, Tag.UNSUPPORTED, Tag.PRINTER]
    assert msg.attrs(Tag.OPERATION) == {
        "attributes-charset": ["utf-8"],
        "attributes-natural-language": ["en"],
        "status-message": ["successful-ok"],
    }
    assert msg.attrs(Tag.UNSUPPORTED) == {"printer-strings-uri": [OutOfBand(Tag.UNSUPPORTED_VALUE)]}
    printer = msg.attrs(Tag.PRINTER)
    assert printer == {
        "printer-name": ["Office laser"],
        "printer-state": [3],
        "printer-state-reasons": ["none"],
        "printer-is-accepting-jobs": [True],
        "printer-make-and-model": ["Example Laser 1000"],
        "printer-info": ["Second floor"],
        "printer-uri-supported": [URI],
        "reference-uri-schemes-supported": ["http"],
        "generated-natural-language-supported": ["en"],
        "document-format-supported": ["application/pdf", "image/urf"],
        "media-supported": ["iso_a4_210x297mm", "na_letter_8.5x11in"],
        "printer-resolution-supported": [Resolution(600, 600, 3), Resolution(1200, 600, 3)],
        "copies-supported": [Range(1, 999)],
        "media-col-default": [
            Collection(
                {
                    "media-size": [Collection({"x-dimension": [21000], "y-dimension": [29700]})],
                    "media-type": ["stationery"],
                    "media-source": ["main-tray"],
                }
            )
        ],
        "printer-current-time": [bytes([0x07, 0xEA, 11, 5, 14, 30, 0, 0, ord("+"), 1, 0])],
        "printer-alert": [b"code=other"],
        "marker-levels": [80, -3],
        "printer-geo-location": [OutOfBand(Tag.NO_VALUE)],
        "printer-organization": [OutOfBand(Tag.UNKNOWN)],
    }
    # Python types, not just equality: bool must not come back as int and vice versa.
    assert type(printer["printer-is-accepting-jobs"][0]) is bool
    assert type(printer["printer-state"][0]) is int
    tags = {a.name: a.tag for a in msg.groups[2].attrs}
    assert tags["printer-state"] == Tag.ENUM
    assert tags["printer-name"] == Tag.NAME_LANG
    assert tags["printer-current-time"] == Tag.DATETIME


def test_response_reencodes_byte_identical() -> None:
    raw = _fixture("gpa_response.bin")
    msg, _ = decode(raw)
    assert encode(msg) == raw


def test_print_job_request_with_media_col() -> None:
    msg = Message(
        version=(1, 1),
        code=OPERATIONS["Print-Job"],
        request_id=2,
        groups=[
            _op_group(
                Attr("requesting-user-name", Tag.NAME, ["labelyard"]),
                Attr("job-name", Tag.NAME, ["Calibration page"]),
                Attr("document-format", Tag.MIME, ["application/pdf"]),
            ),
            Group(
                Tag.JOB,
                [
                    Attr(
                        "media-col",
                        Tag.BEG_COLLECTION,
                        [
                            Collection(
                                {
                                    "media-size": [
                                        Collection({"x-dimension": [21000], "y-dimension": [29700]})
                                    ],
                                    "media-type": ["labels"],
                                    "media-source": ["main-tray"],
                                }
                            )
                        ],
                    ),
                    Attr("copies", Tag.INTEGER, [1]),
                ],
            ),
        ],
    )
    expected = _fixture("print_job_request.bin")

    assert encode(msg) == expected
    decoded, _ = decode(expected)
    assert decoded == msg


def test_print_job_document_is_trailing_bytes() -> None:
    msg = Message((1, 1), OPERATIONS["Print-Job"], 7, [_op_group()])
    document = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n" + bytes(range(256))
    decoded, trailing = decode(encode(msg, document))
    assert trailing == document
    assert decoded == msg


def test_fixture_bytes_are_what_assemble_writes() -> None:
    """The committed .bin files are exactly the hand assembly (no stale fixture)."""
    for name, build in wire.FIXTURES.items():
        assert _fixture(name) == build(), name


# --------------------------------------------------------------------------- unknown tags


@pytest.mark.parametrize(
    ("tag", "raw"),
    [
        (0x7F, b"\x40\x00\x00\x01vendor-extended"),  # RFC 8010 3.5.2 extension tag
        (0x60, b"\x00\x01\x02"),  # reserved for future types
        (0x11, b"\x01"),  # unassigned out-of-band tag with a value (3.8: future use)
        (0x38, b"\xff\xfe"),  # unassigned octetString type
    ],
)
def test_unknown_tag_preserved(tag: int, raw: bytes) -> None:
    data = _minimal(
        wire.attr(0x47, "attributes-charset", b"utf-8"), wire.attr(tag, "x-vendor", raw)
    )
    msg, _ = decode(data)
    assert msg.attrs(Tag.OPERATION)["x-vendor"] == [Unknown(tag, raw)]
    assert encode(msg) == data


@pytest.mark.parametrize(
    "tag",
    [
        0x15,  # not-settable (RFC 3380)
        0x16,  # delete-attribute (RFC 3380)
        0x17,  # admin-define (RFC 3380)
        0x11,  # unassigned, zero length
        0x14,  # unassigned, zero length
        0x1F,  # last tag of the out-of-band range
    ],
)
def test_every_zero_length_out_of_band_tag_is_out_of_band(tag: int) -> None:
    data = _minimal(wire.attr(0x47, "attributes-charset", b"utf-8"), wire.attr(tag, "x-oob", b""))
    msg, _ = decode(data)
    assert msg.attrs(Tag.OPERATION)["x-oob"] == [OutOfBand(tag)]
    assert encode(msg) == data


def test_registered_out_of_band_tags_are_named() -> None:
    assert (Tag.NOT_SETTABLE, Tag.DELETE_ATTRIBUTE, Tag.ADMIN_DEFINE) == (0x15, 0x16, 0x17)


@pytest.mark.parametrize("tag", [0x15, 0x16, 0x17])
def test_registered_out_of_band_tag_with_a_value_is_rejected(tag: int) -> None:
    data = _minimal(wire.attr(tag, "x-oob", b"\x00"))
    with pytest.raises(IppDecodeError) as err:
        decode(data)
    assert err.value.reason == "out_of_band_length"


def test_unknown_delimiter_group_kept_but_not_read() -> None:
    data = (
        wire.HEADER_OK
        + bytes([0x01])
        + wire.attr(0x47, "attributes-charset", b"utf-8")
        + bytes([0x0E])  # unassigned delimiter tag (0x06-0x0f)
        + wire.attr(0x44, "printer-state-reasons", b"media-empty")
        + bytes([0x04])
        + wire.attr(0x23, "printer-state", wire.i32(4))
        + wire.END_OF_ATTRIBUTES
    )
    msg, _ = decode(data)
    assert [g.tag for g in msg.groups] == [Tag.OPERATION, 0x0E, Tag.PRINTER]
    assert msg.attrs(Tag.PRINTER) == {"printer-state": [4]}
    assert "printer-state-reasons" not in msg.attrs(Tag.OPERATION)
    assert encode(msg) == data


def test_attrs_reads_first_group_and_first_duplicate() -> None:
    data = (
        wire.HEADER_OK
        + bytes([0x02])
        + wire.attr(0x21, "job-id", wire.i32(5))
        + wire.attr(0x21, "job-id", wire.i32(6))  # malformed duplicate, ignored by attrs()
        + bytes([0x02])
        + wire.attr(0x21, "job-id", wire.i32(9))
        + wire.END_OF_ATTRIBUTES
    )
    msg, _ = decode(data)
    assert msg.attrs(Tag.JOB) == {"job-id": [5]}
    assert msg.attrs(Tag.PRINTER) == {}
    assert len(msg.groups) == 2


def test_mixed_syntax_attribute_roundtrips() -> None:
    """``number-up-supported`` is 1setOf (integer | rangeOfInteger)."""
    data = _minimal(
        wire.attr(0x21, "number-up-supported", wire.i32(1)),
        wire.more(0x33, wire.i32(2) + wire.i32(16)),
        wire.more(0x13, b""),
        group=0x04,
    )
    msg, _ = decode(data)
    assert msg.attrs(Tag.PRINTER)["number-up-supported"] == [1, Range(2, 16), OutOfBand(0x13)]
    assert encode(msg) == data


def test_collection_member_tags_preserved_on_reencode() -> None:
    data = _minimal(
        wire.attr(0x34, "media-col-ready", b""),
        wire.member("media-key"),
        wire.more(0x42, b"tray-1-labels"),  # name, not the inferred keyword
        wire.member("media-source-properties-feed"),
        wire.more(0x23, wire.i32(4)),  # enum, not the inferred integer
        wire.more(0x23, wire.i32(5)),  # additional value of the same member
        wire.END_COLLECTION,
        wire.BEG_NAMELESS,  # second value of media-col-ready (1setOf collection)
        wire.member("media-key"),
        wire.more(0x44, b"plain"),
        wire.END_COLLECTION,
        group=0x04,
    )
    msg, _ = decode(data)
    assert msg.attrs(Tag.PRINTER)["media-col-ready"] == [
        Collection({"media-key": ["tray-1-labels"], "media-source-properties-feed": [4, 5]}),
        Collection({"media-key": ["plain"]}),
    ]
    assert encode(msg) == data


def test_member_name_with_empty_value_continues_member() -> None:
    """RFC 8010 3.1.7: 'Additional member attribute values are specified using a value
    length of 0' — accepted as an alternative to the plain additional-value form."""
    data = _minimal(
        wire.attr(0x34, "c", b""),
        wire.member("m"),
        wire.more(0x44, b"a"),
        wire.more(0x4A, b""),
        wire.more(0x44, b"b"),
        wire.END_COLLECTION,
    )
    msg, _ = decode(data)
    assert msg.attrs(Tag.OPERATION)["c"] == [Collection({"m": ["a", "b"]})]


def test_hand_built_collection_infers_member_tags() -> None:
    msg = Message(
        (1, 1),
        2,
        3,
        [
            Group(
                Tag.JOB,
                [
                    Attr(
                        "c",
                        Tag.BEG_COLLECTION,
                        [Collection({"k": ["v"], "n": [1], "b": [True], "o": [b"\x00"]})],
                    )
                ],
            )
        ],
    )
    data = encode(msg)
    assert wire.member("k") + wire.more(0x44, b"v") in data
    assert wire.member("n") + wire.more(0x21, wire.i32(1)) in data
    assert wire.member("b") + wire.more(0x22, b"\x01") in data
    assert wire.member("o") + wire.more(0x30, b"\x00") in data
    assert decode(data)[0] == msg


def test_text_with_language_encodes_with_message_language() -> None:
    msg = Message(
        (1, 1),
        0,
        1,
        [
            Group(
                Tag.OPERATION,
                [
                    Attr("attributes-charset", Tag.CHARSET, ["utf-8"]),
                    Attr("attributes-natural-language", Tag.LANGUAGE, ["de"]),
                    Attr("status-message", Tag.TEXT_LANG, ["fertig"]),
                ],
            )
        ],
    )
    data = encode(msg)
    assert wire.attr(0x35, "status-message", wire.with_language(b"de", b"fertig")) in data


# --------------------------------------------------------------------------- bounds


def _nested(depth: int) -> bytes:
    """A collection attribute nested ``depth`` levels deep (top level counts as 1)."""
    body = wire.attr(0x34, "c", b"")
    for _ in range(depth - 1):
        body += wire.member("m") + wire.BEG_NAMELESS
    return body + wire.END_COLLECTION * depth


def _many_values(n: int) -> bytes:
    return wire.attr(0x21, "x", wire.i32(0)) + wire.more(0x21, wire.i32(0)) * (n - 1)


def test_depth_at_limit_accepted() -> None:
    msg, _ = decode(_minimal(_nested(MAX_DEPTH)))
    value = msg.attrs(Tag.OPERATION)["c"][0]
    for _ in range(MAX_DEPTH - 1):
        assert isinstance(value, Collection)
        value = value.members["m"][0]
    assert value == Collection({})


def test_values_at_limit_accepted() -> None:
    msg, _ = decode(_minimal(_many_values(MAX_VALUES)))
    assert len(msg.attrs(Tag.OPERATION)["x"]) == MAX_VALUES


def test_limits_have_the_specified_values() -> None:
    assert MAX_DEPTH == 8
    assert MAX_VALUES == 10_000


HEADER = wire.HEADER_GPA


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        pytest.param(b"", "truncated", id="empty"),
        pytest.param(HEADER[:7], "truncated", id="seven_byte_header"),
        pytest.param(HEADER, "missing_end_tag", id="header_only"),
        pytest.param(
            HEADER + b"\x01" + b"\x44" + wire.u16(1) + b"x" + wire.u16(10) + b"abc",
            "truncated",
            id="value_length_past_end",
        ),
        pytest.param(
            HEADER + b"\x01" + b"\x44" + wire.u16(40) + b"short-name",
            "truncated",
            id="name_past_end",
        ),
        pytest.param(
            HEADER + b"\x01" + wire.attr(0x44, "a", b"b"), "missing_end_tag", id="missing_end_tag"
        ),
        pytest.param(_minimal(_nested(MAX_DEPTH + 1)), "depth_exceeded", id="collection_depth_9"),
        pytest.param(_minimal(_many_values(MAX_VALUES + 1)), "too_many_values", id="10001_values"),
        pytest.param(
            _minimal(wire.attr(0x44, "a", b"b"), wire.END_COLLECTION),
            "unexpected_end_collection",
            id="end_collection_without_begin",
        ),
        pytest.param(
            _minimal(wire.END_COLLECTION),
            "unexpected_end_collection",
            id="end_collection_first_in_group",
        ),
        pytest.param(
            _minimal(wire.attr(0x21, "n", b"\x00\x00\x01")), "bad_value_length", id="integer_len_3"
        ),
        pytest.param(
            _minimal(wire.attr(0x22, "b", b"\x01\x00")), "bad_value_length", id="boolean_len_2"
        ),
        pytest.param(_minimal(wire.attr(0x22, "b", b"\x02")), "bad_boolean", id="boolean_value_2"),
        pytest.param(
            _minimal(wire.attr(0x32, "r", b"\x00" * 8)), "bad_value_length", id="resolution_len_8"
        ),
        pytest.param(
            _minimal(wire.attr(0x33, "r", b"\x00" * 7)), "bad_value_length", id="range_len_7"
        ),
        pytest.param(
            _minimal(wire.attr(0x31, "d", b"\x00" * 10)), "bad_value_length", id="datetime_len_10"
        ),
        pytest.param(
            _minimal(wire.attr(0x13, "o", b"x")), "out_of_band_length", id="no_value_with_bytes"
        ),
        pytest.param(
            _minimal(wire.attr(0x35, "t", wire.u16(9) + b"en")), "bad_with_language", id="lang_past"
        ),
        pytest.param(
            _minimal(wire.attr(0x36, "t", wire.with_language(b"en", b"x") + b"!")),
            "bad_with_language",
            id="lang_trailing",
        ),
        pytest.param(
            HEADER + b"\x01" + b"\x44" + b"\x80\x00", "negative_length", id="negative_name_length"
        ),
        pytest.param(
            HEADER + b"\x01" + b"\x44" + wire.u16(1) + b"a" + b"\xff\xff",
            "negative_length",
            id="negative_value_length",
        ),
        pytest.param(
            HEADER + wire.attr(0x44, "a", b"b") + wire.END_OF_ATTRIBUTES,
            "attribute_outside_group",
            id="value_before_group",
        ),
        pytest.param(
            _minimal(wire.more(0x44, b"b")),
            "additional_value_without_attribute",
            id="additional_value_first",
        ),
        pytest.param(HEADER + b"\x00" + wire.END_OF_ATTRIBUTES, "reserved_tag", id="tag_0x00"),
        pytest.param(
            _minimal(wire.member("m")),
            "unexpected_member_name",
            id="member_name_outside_collection",
        ),
        pytest.param(
            HEADER + b"\x01" + wire.attr(0x34, "c", b"") + wire.member("m") + b"\x04" + b"\x03",
            "unterminated_collection",
            id="delimiter_inside_collection",
        ),
        pytest.param(
            HEADER + b"\x01" + wire.attr(0x34, "c", b""), "truncated", id="collection_cut_off"
        ),
        pytest.param(
            _minimal(wire.attr(0x34, "c", b""), wire.more(0x44, b"v"), wire.END_COLLECTION),
            "member_without_name",
            id="member_value_without_name",
        ),
        pytest.param(
            _minimal(wire.attr(0x34, "c", b""), wire.more(0x4A, b""), wire.more(0x44, b"v")),
            "member_without_name",
            id="empty_member_name_first",
        ),
        pytest.param(
            _minimal(wire.attr(0x34, "c", b""), wire.member("m"), wire.attr(0x44, "x", b"v")),
            "member_name_length",
            id="named_value_inside_collection",
        ),
        pytest.param(
            _minimal(
                wire.attr(0x34, "c", b""),
                wire.member("m"),
                wire.more(0x44, b"v"),
                wire.member("m"),
                wire.more(0x44, b"w"),
                wire.END_COLLECTION,
            ),
            "duplicate_member",
            id="duplicate_member",
        ),
        pytest.param(
            _minimal(wire.attr(0x34, "c", b""), wire.member("m"), wire.END_COLLECTION),
            "member_without_value",
            id="member_name_then_end",
        ),
        pytest.param(
            _minimal(wire.attr(0x34, "c", b""), wire.member("m"), wire.member("n")),
            "member_without_value",
            id="member_name_then_member_name",
        ),
        pytest.param(
            _minimal(
                wire.attr(0x34, "c", b""),
                wire.member("m"),
                wire.more(0x44, b"v"),
                b"\x37" + wire.u16(1) + b"x" + wire.u16(0),
            ),
            "bad_end_collection",
            id="end_collection_with_name",
        ),
    ],
)
def test_decode_rejects(data: bytes, reason: str) -> None:
    with pytest.raises(IppDecodeError) as exc:
        decode(data)
    assert exc.value.reason == reason


def test_decode_rejects_too_many_attributes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(codec, "MAX_ATTRIBUTES", 3)
    data = _minimal(*(wire.attr(0x44, f"a{i}", b"v") for i in range(4)))
    with pytest.raises(IppDecodeError) as exc:
        decode(data)
    assert exc.value.reason == "too_many_attributes"
    decode(_minimal(*(wire.attr(0x44, f"a{i}", b"v") for i in range(3))))


def test_decode_rejects_too_many_groups(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(codec, "MAX_GROUPS", 2)
    with pytest.raises(IppDecodeError) as exc:
        decode(HEADER + b"\x02\x02\x02" + wire.END_OF_ATTRIBUTES)
    assert exc.value.reason == "too_many_groups"
    decode(HEADER + b"\x02\x02" + wire.END_OF_ATTRIBUTES)


def test_decode_rejects_too_many_values_in_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(codec, "MAX_TOTAL_VALUES", 5)
    data = _minimal(*(wire.attr(0x21, f"n{i}", wire.i32(i)) for i in range(6)))
    with pytest.raises(IppDecodeError) as exc:
        decode(data)
    assert exc.value.reason == "too_many_values"


def test_member_values_count_against_the_value_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(codec, "MAX_VALUES", 3)
    data = _minimal(
        wire.attr(0x34, "c", b""),
        wire.member("m"),
        *(wire.more(0x21, wire.i32(i)) for i in range(4)),
        wire.END_COLLECTION,
    )
    with pytest.raises(IppDecodeError) as exc:
        decode(data)
    assert exc.value.reason == "too_many_values"


def test_decode_accepts_bytearray_and_memoryview() -> None:
    raw = _fixture("gpa_request.bin")
    assert decode(bytearray(raw))[0] == decode(raw)[0]
    assert decode(memoryview(raw))[0] == decode(raw)[0]


def test_invalid_utf8_is_replaced_not_raised() -> None:
    msg, _ = decode(_minimal(wire.attr(0x41, "printer-info", b"caf\xe9")))
    assert msg.attrs(Tag.OPERATION)["printer-info"] == ["caf�"]


# --------------------------------------------------------------------------- hostile fuzz


@pytest.mark.parametrize("name", sorted(wire.FIXTURES))
def test_every_truncation_is_a_decode_error(name: str) -> None:
    raw = _fixture(name)
    for cut in range(len(raw)):
        with pytest.raises(IppDecodeError):
            decode(raw[:cut])


@pytest.mark.parametrize("name", sorted(wire.FIXTURES))
def test_random_mutations_never_raise_anything_else(name: str) -> None:
    rng = random.Random(f"ipp-mutate-{name}")
    raw = _fixture(name)
    for _ in range(3000):
        data = bytearray(raw)
        for _ in range(rng.randint(1, 4)):
            pos = rng.randrange(len(data))
            op = rng.random()
            if op < 0.6:
                data[pos] = rng.randrange(256)
            elif op < 0.8:
                del data[pos]
            else:
                data.insert(pos, rng.randrange(256))
        with contextlib.suppress(IppDecodeError):
            decode(bytes(data))


def test_random_bytes_never_raise_anything_else() -> None:
    rng = random.Random("ipp-random")
    for _ in range(3000):
        data = HEADER + bytes(rng.randrange(256) for _ in range(rng.randint(0, 64)))
        with contextlib.suppress(IppDecodeError):
            decode(data)


# --------------------------------------------------------------------------- property round trip


_PLAIN = [
    Tag.INTEGER,
    Tag.ENUM,
    Tag.BOOLEAN,
    Tag.OCTET_STRING,
    Tag.DATETIME,
    Tag.RESOLUTION,
    Tag.RANGE,
    Tag.TEXT,
    Tag.NAME,
    Tag.KEYWORD,
    Tag.URI,
    Tag.URI_SCHEME,
    Tag.CHARSET,
    Tag.LANGUAGE,
    Tag.MIME,
]


def _value(rng: random.Random, tag: Tag) -> codec.Value:
    if tag in (Tag.INTEGER, Tag.ENUM):
        return rng.randint(-(2**31), 2**31 - 1)
    if tag is Tag.BOOLEAN:
        return rng.random() < 0.5
    if tag is Tag.OCTET_STRING:
        return bytes(rng.randrange(256) for _ in range(rng.randint(0, 12)))
    if tag is Tag.DATETIME:
        return bytes(rng.randrange(256) for _ in range(11))
    if tag is Tag.RESOLUTION:
        return Resolution(rng.randint(-5, 2400), rng.randint(0, 2400), rng.choice([3, 4, -1]))
    if tag is Tag.RANGE:
        return Range(rng.randint(-10, 10), rng.randint(10, 2**31 - 1))
    alphabet = "abcxyz-_.:/ äöü€"
    return "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 20)))


def _collection(rng: random.Random, depth: int) -> Collection:
    members: dict[str, list[codec.Value]] = {}
    for i in range(rng.randint(0, 4)):
        if depth < MAX_DEPTH and rng.random() < 0.3:
            members[f"m{i}"] = [_collection(rng, depth + 1) for _ in range(rng.randint(1, 2))]
        else:
            tag = rng.choice([Tag.INTEGER, Tag.BOOLEAN, Tag.OCTET_STRING, Tag.KEYWORD])
            members[f"m{i}"] = [_value(rng, tag) for _ in range(rng.randint(1, 3))]
    return Collection(members)


def _message(rng: random.Random) -> Message:
    groups = []
    for _ in range(rng.randint(0, 4)):
        attrs = []
        for i in range(rng.randint(0, 6)):
            roll = rng.random()
            if roll < 0.15:
                attrs.append(
                    Attr(f"c{i}", Tag.BEG_COLLECTION, [_collection(rng, 1) for _ in range(2)])
                )
            elif roll < 0.25:
                attrs.append(Attr(f"o{i}", Tag.NO_VALUE, [OutOfBand(Tag.NO_VALUE)]))
            else:
                tag = rng.choice(_PLAIN)
                values = [_value(rng, tag) for _ in range(rng.randint(1, 4))]
                if rng.random() < 0.2:
                    values.append(Unknown(0x7F, b"\x00\x01"))
                attrs.append(Attr(f"a{i}", tag, values))
        groups.append(Group(rng.choice([Tag.OPERATION, Tag.JOB, Tag.PRINTER, 0x09]), attrs))
    return Message(
        (rng.randint(1, 2), rng.randint(0, 1)),
        rng.randint(0, 0x7FFF),
        rng.randint(1, 2**31 - 1),
        groups,
    )


def test_property_roundtrip() -> None:
    rng = random.Random("ipp-roundtrip")
    for _ in range(500):
        msg = _message(rng)
        document = bytes(rng.randrange(256) for _ in range(rng.randint(0, 8)))
        data = encode(msg, document)
        decoded, trailing = decode(data)
        assert decoded == msg
        assert trailing == document
        assert encode(decoded, document) == data


# --------------------------------------------------------------------------- encode errors


def _encode_one(attr: Attr) -> bytes:
    return encode(Message((1, 1), 2, 1, [Group(Tag.JOB, [attr])]))


@pytest.mark.parametrize(
    "attr",
    [
        pytest.param(Attr("empty", Tag.KEYWORD, []), id="no_values"),
        pytest.param(Attr("", Tag.KEYWORD, ["v"]), id="empty_name"),
        pytest.param(Attr("x" * 32768, Tag.KEYWORD, ["v"]), id="name_too_long"),
        pytest.param(Attr("v", Tag.TEXT, ["x" * 32768]), id="value_too_long"),
        pytest.param(Attr("i", Tag.INTEGER, [2**31]), id="integer_overflow"),
        pytest.param(Attr("d", Tag.DATETIME, [b"\x00" * 10]), id="datetime_len"),
        pytest.param(Attr("o", Tag.NO_VALUE, [OutOfBand(0x21)]), id="out_of_band_bad_tag"),
        pytest.param(Attr("u", Tag.KEYWORD, [Unknown(0x34, b"")]), id="unknown_structural_tag"),
        pytest.param(Attr("u", Tag.KEYWORD, [Unknown(0x03, b"")]), id="unknown_delimiter_tag"),
        pytest.param(Attr("r", Tag.RESOLUTION, [Resolution(1, 1, 300)]), id="units_overflow"),
        pytest.param(
            Attr("c", Tag.BEG_COLLECTION, [Collection({"": ["v"]})]), id="empty_member_name"
        ),
        pytest.param(
            Attr("c", Tag.BEG_COLLECTION, [Collection({"m": []})]), id="member_without_values"
        ),
    ],
)
def test_encode_rejects(attr: Attr) -> None:
    with pytest.raises(IppEncodeError):
        _encode_one(attr)


def test_encode_rejects_collection_deeper_than_limit() -> None:
    value: codec.Value = Collection({})
    for _ in range(MAX_DEPTH):
        value = Collection({"m": [value]})
    with pytest.raises(IppEncodeError):
        _encode_one(Attr("c", Tag.BEG_COLLECTION, [value]))


@pytest.mark.parametrize("tag", [0x00, 0x03, 0x10, 0x100])
def test_encode_rejects_bad_group_tag(tag: int) -> None:
    with pytest.raises(IppEncodeError):
        encode(Message((1, 1), 2, 1, [Group(tag, [])]))


def test_encode_rejects_bad_header() -> None:
    with pytest.raises(IppEncodeError):
        encode(Message((1, 1), 2, 2**31, []))
    with pytest.raises(IppEncodeError):
        encode(Message((300, 1), 2, 1, []))


def test_value_type_mismatch_uses_the_value_type() -> None:
    """A value that does not fit Attr.tag is encoded with the tag of its own type."""
    data = _encode_one(Attr("x", Tag.KEYWORD, [5, True, Range(1, 2), Resolution(3, 4, 3)]))
    assert wire.attr(0x21, "x", wire.i32(5)) + wire.more(0x22, b"\x01") in data
    assert wire.more(0x33, wire.i32(1) + wire.i32(2)) in data
    assert wire.more(0x32, wire.i32(3) + wire.i32(4) + b"\x03") in data


def test_encode_rejects_values_of_foreign_types() -> None:
    with pytest.raises(IppEncodeError):
        _encode_one(Attr("f", Tag.INTEGER, [1.5]))  # type: ignore[list-item]
    with pytest.raises(IppEncodeError):
        _encode_one(Attr("c", Tag.BEG_COLLECTION, [Collection({"f": [None]})]))  # type: ignore[list-item]


def test_text_with_language_defaults_to_en_without_message_language() -> None:
    data = _encode_one(Attr("job-message", Tag.TEXT_LANG, ["done"]))
    assert wire.attr(0x35, "job-message", wire.with_language(b"en", b"done")) in data


# --------------------------------------------------------------------------- tables


def test_operations_table() -> None:
    assert OPERATIONS == {
        "Print-Job": 0x0002,
        "Validate-Job": 0x0004,
        "Cancel-Job": 0x0008,
        "Get-Job-Attributes": 0x0009,
        "Get-Jobs": 0x000A,
        "Get-Printer-Attributes": 0x000B,
    }


def test_status_names_table() -> None:
    expected_codes = (
        set(range(0x0000, 0x0003))
        | (set(range(0x0400, 0x0421)) - {0x0416, 0x0417})  # 0x0416/0x0417 reserved (IANA)
        | set(range(0x0500, 0x050D))
    )
    assert set(STATUS_NAMES) == expected_codes
    assert STATUS_NAMES[0x0000] == "successful-ok"
    assert STATUS_NAMES[0x0406] == "client-error-not-found"
    assert STATUS_NAMES[0x040A] == "client-error-document-format-not-supported"
    assert STATUS_NAMES[0x040B] == "client-error-attributes-or-values-not-supported"
    assert STATUS_NAMES[0x0420] == "client-error-not-fetchable"
    assert STATUS_NAMES[0x0507] == "server-error-busy"
    assert STATUS_NAMES[0x050C] == "server-error-too-many-documents"
    for code, status in STATUS_NAMES.items():
        prefix = {0x00: "successful-", 0x04: "client-error-", 0x05: "server-error-"}[code >> 8]
        assert status.startswith(prefix), (hex(code), status)
