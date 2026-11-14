# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Hand assembly of the synthetic IPP fixtures in this directory.

Run ``python assemble.py`` from this directory to rewrite the ``.bin`` files.

The bytes are spelled out field by field from RFC 8010 section 3 (header 3.1.1,
attribute 3.1.3-3.1.5, collection 3.1.6, member attribute 3.1.7, tags 3.5,
value encodings 3.9). This module deliberately does not import the hub's codec:
the fixtures are an independent statement of the wire format, so a codec bug
cannot be reproduced into its own expected output.

All values are synthetic. Hosts use ``printer.example.invalid``.
"""

from __future__ import annotations

from pathlib import Path


def u16(n: int) -> bytes:
    """SIGNED-SHORT, big-endian (RFC 8010 section 3)."""
    return n.to_bytes(2, "big", signed=True)


def i32(n: int) -> bytes:
    """SIGNED-INTEGER, big-endian."""
    return n.to_bytes(4, "big", signed=True)


def attr(tag: int, name: str, value: bytes) -> bytes:
    """attribute-with-one-value (3.1.4): tag, name-length, name, value-length, value."""
    n = name.encode("ascii")
    return bytes([tag]) + u16(len(n)) + n + u16(len(value)) + value


def more(tag: int, value: bytes) -> bytes:
    """additional-value (3.1.5): tag, name-length 0, value-length, value."""
    return bytes([tag]) + u16(0) + u16(len(value)) + value


def member(name: str) -> bytes:
    """memberAttrName (3.1.7): tag 0x4a, name-length 0, value = member name."""
    return more(0x4A, name.encode("ascii"))


BEG_NAMELESS = bytes([0x34]) + u16(0) + u16(0)  # begCollection as member/additional value
END_COLLECTION = bytes([0x37]) + u16(0) + u16(0)  # endCollection (3.1.6)
END_OF_ATTRIBUTES = bytes([0x03])  # end-of-attributes-tag (3.5.1)

HEADER_GPA = bytes([0x01, 0x01]) + u16(0x000B) + i32(1)  # 1.1, Get-Printer-Attributes, id 1
HEADER_OK = bytes([0x01, 0x01]) + u16(0x0000) + i32(1)  # 1.1, successful-ok, id 1
HEADER_PRINT = bytes([0x01, 0x01]) + u16(0x0002) + i32(2)  # 1.1, Print-Job, id 2

URI = b"ipp://printer.example.invalid/ipp/print"


def with_language(lang: bytes, text: bytes) -> bytes:
    """textWithLanguage / nameWithLanguage value (3.9, Table 7)."""
    return u16(len(lang)) + lang + u16(len(text)) + text


def gpa_request() -> bytes:
    return (
        HEADER_GPA
        + bytes([0x01])  # operation-attributes-tag
        + attr(0x47, "attributes-charset", b"utf-8")
        + attr(0x48, "attributes-natural-language", b"en")
        + attr(0x45, "printer-uri", URI)
        + attr(0x44, "requested-attributes", b"printer-state")
        + more(0x44, b"marker-levels")
        + END_OF_ATTRIBUTES
    )


def gpa_response() -> bytes:
    # RFC 2579 DateAndTime: 2026-11-05 14:30:00.0 +01:00
    datetime_value = bytes([0x07, 0xEA, 11, 5, 14, 30, 0, 0, ord("+"), 1, 0])
    return (
        HEADER_OK
        + bytes([0x01])  # operation-attributes-tag
        + attr(0x47, "attributes-charset", b"utf-8")
        + attr(0x48, "attributes-natural-language", b"en")
        + attr(0x35, "status-message", with_language(b"en", b"successful-ok"))
        + bytes([0x05])  # unsupported-attributes-tag
        + attr(0x10, "printer-strings-uri", b"")  # out-of-band 'unsupported'
        + bytes([0x04])  # printer-attributes-tag
        + attr(0x36, "printer-name", with_language(b"en", b"Office laser"))
        + attr(0x23, "printer-state", i32(3))  # idle
        + attr(0x44, "printer-state-reasons", b"none")
        + attr(0x22, "printer-is-accepting-jobs", b"\x01")
        + attr(0x41, "printer-make-and-model", b"Example Laser 1000")
        + attr(0x42, "printer-info", b"Second floor")
        + attr(0x45, "printer-uri-supported", URI)
        + attr(0x46, "reference-uri-schemes-supported", b"http")
        + attr(0x48, "generated-natural-language-supported", b"en")
        + attr(0x49, "document-format-supported", b"application/pdf")
        + more(0x49, b"image/urf")
        + attr(0x44, "media-supported", b"iso_a4_210x297mm")  # 1setOf keyword
        + more(0x44, b"na_letter_8.5x11in")
        + attr(0x32, "printer-resolution-supported", i32(600) + i32(600) + bytes([3]))
        + more(0x32, i32(1200) + i32(600) + bytes([3]))
        + attr(0x33, "copies-supported", i32(1) + i32(999))
        + attr(0x34, "media-col-default", b"")
        + member("media-size")
        + BEG_NAMELESS
        + member("x-dimension")
        + more(0x21, i32(21000))
        + member("y-dimension")
        + more(0x21, i32(29700))
        + END_COLLECTION
        + member("media-type")
        + more(0x44, b"stationery")
        + member("media-source")
        + more(0x44, b"main-tray")
        + END_COLLECTION
        + attr(0x31, "printer-current-time", datetime_value)
        + attr(0x30, "printer-alert", b"code=other")
        + attr(0x21, "marker-levels", i32(80))
        + more(0x21, i32(-3))
        + attr(0x13, "printer-geo-location", b"")  # out-of-band 'no-value'
        + attr(0x12, "printer-organization", b"")  # out-of-band 'unknown'
        + END_OF_ATTRIBUTES
    )


def print_job_request() -> bytes:
    """Print-Job with media-col{media-size{x, y}, media-type, media-source} (3.1.6, 3.1.7)."""
    return (
        HEADER_PRINT
        + bytes([0x01])  # operation-attributes-tag
        + attr(0x47, "attributes-charset", b"utf-8")
        + attr(0x48, "attributes-natural-language", b"en")
        + attr(0x45, "printer-uri", URI)
        + attr(0x42, "requesting-user-name", b"labelyard")
        + attr(0x42, "job-name", b"Calibration page")
        + attr(0x49, "document-format", b"application/pdf")
        + bytes([0x02])  # job-attributes-tag
        + attr(0x34, "media-col", b"")  # begCollection, value-length 0
        + member("media-size")
        + BEG_NAMELESS  # nested collection as the member value
        + member("x-dimension")
        + more(0x21, i32(21000))
        + member("y-dimension")
        + more(0x21, i32(29700))
        + END_COLLECTION
        + member("media-type")
        + more(0x44, b"labels")
        + member("media-source")
        + more(0x44, b"main-tray")
        + END_COLLECTION
        + attr(0x21, "copies", i32(1))
        + END_OF_ATTRIBUTES
    )


FIXTURES = {
    "gpa_request.bin": gpa_request,
    "gpa_response.bin": gpa_response,
    "print_job_request.bin": print_job_request,
}


if __name__ == "__main__":
    here = Path(__file__).parent
    for name, build in FIXTURES.items():
        (here / name).write_bytes(build())
