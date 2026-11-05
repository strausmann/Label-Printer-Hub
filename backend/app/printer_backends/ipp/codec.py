"""Pure encoder/decoder for the IPP/1.1 binary message format (RFC 8010).

No I/O, no IPP library. The decoder parses bytes that come from a network
device, so every step is bounded and every malformed input ends in
``IppDecodeError`` with a stable ``reason``:

* lengths are checked against the remaining buffer before slicing (no
  over-read, no allocation driven by a length field);
* collection nesting is limited to ``MAX_DEPTH``, values per attribute (and per
  collection member) to ``MAX_VALUES``, attributes, groups and values per
  message to ``MAX_ATTRIBUTES``, ``MAX_GROUPS`` and ``MAX_TOTAL_VALUES``;
* parsing is a single forward pass, so it terminates after at most
  ``len(data)`` steps.

The size of the input itself is bounded by the caller (the client caps a
response body at 1 MB, spec 11.2).

Representation choices (all documented here so later tasks can rely on them):

* ``Attr.tag`` is the wire tag of the attribute's first value. Values carry
  their own type; ``OutOfBand`` and ``Unknown`` carry their own tag.
* ``textWithLanguage`` / ``nameWithLanguage`` decode to their text (``str``);
  the encoder writes a ``str`` under those tags with the message's
  ``attributes-natural-language`` (``en`` if absent).
* ``dateTime`` and ``octetString`` decode to ``bytes``.
* Wire tags of individual values (attribute values and collection members) are
  remembered on decode in non-compared fields, so decode then encode is
  byte-identical even where one Python type maps to several tags (keyword vs.
  name, integer vs. enum). Hand-built values without that record get the tag of
  ``Attr.tag`` if it fits the value's type, else a tag inferred from the type
  (``str`` → keyword, ``int`` → integer, ...).
* Unknown value tags decode to ``Unknown(tag, raw)`` and re-encode as they came
  (RFC 8010 3.5.2 asks a parser to treat unknown tags atomically). ``Unknown``
  is also the escape hatch to emit raw bytes under any non-structural tag.
* An unassigned delimiter tag in 0x06-0x0f starts a group that is kept in
  ``Message.groups`` with its integer tag; ``Message.attrs`` never reads it.

Strings are decoded as UTF-8 with replacement characters for invalid bytes
(the hub always sends ``attributes-charset=utf-8``); a printer cannot make the
decoder raise through text content.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum

from app.printer_backends.ipp.errors import IppDecodeError, IppEncodeError

MAX_DEPTH = 8
"""Deepest collection nesting accepted; a top-level collection value is depth 1."""

MAX_VALUES = 10_000
"""Most values in one attribute or one collection member."""

MAX_ATTRIBUTES = 10_000
"""Most attributes (including collection members) in one message."""

MAX_GROUPS = 1_000
"""Most attribute groups in one message (Get-Jobs returns one group per job)."""

MAX_TOTAL_VALUES = 100_000
"""Most values (including collection members' values) in one message."""

_MAX_LENGTH = 0x7FFF  # name-length / value-length are SIGNED-SHORT (RFC 8010 3.6, 3.8)
_HEADER_LENGTH = 8  # version-number 2, operation-id/status-code 2, request-id 4 (3.1.1)


class Tag(IntEnum):
    """Delimiter tags (RFC 8010 3.5.1) and value tags (3.5.2) the hub knows."""

    # delimiter tags, Table 2
    OPERATION = 0x01
    JOB = 0x02
    END = 0x03
    PRINTER = 0x04
    UNSUPPORTED = 0x05
    # out-of-band value tags, Table 3
    UNSUPPORTED_VALUE = 0x10
    UNKNOWN = 0x12
    NO_VALUE = 0x13
    # integer tags, Table 4
    INTEGER = 0x21
    BOOLEAN = 0x22
    ENUM = 0x23
    # octetString tags, Table 5
    OCTET_STRING = 0x30
    DATETIME = 0x31
    RESOLUTION = 0x32
    RANGE = 0x33
    BEG_COLLECTION = 0x34
    TEXT_LANG = 0x35
    NAME_LANG = 0x36
    END_COLLECTION = 0x37
    # character-string tags, Table 6
    TEXT = 0x41
    NAME = 0x42
    KEYWORD = 0x44
    URI = 0x45
    URI_SCHEME = 0x46
    CHARSET = 0x47
    LANGUAGE = 0x48
    MIME = 0x49
    MEMBER_NAME = 0x4A


@dataclass(frozen=True)
class Resolution:
    """``resolution`` (RFC 8010 3.9): cross-feed, feed, units (3 = dpi, 4 = dpcm)."""

    x: int
    y: int
    units: int


@dataclass(frozen=True)
class Range:
    """``rangeOfInteger`` (RFC 8010 3.9)."""

    lower: int
    upper: int


@dataclass
class Collection:
    """``collection`` (RFC 8010 3.1.6): member name → values, in wire order."""

    members: dict[str, list[Value]]
    member_tags: dict[str, list[int]] = field(default_factory=dict, compare=False, repr=False)


@dataclass(frozen=True)
class OutOfBand:
    """Out-of-band value such as ``no-value`` or ``unsupported`` (RFC 8010 3.5.2, Table 3)."""

    tag: int


@dataclass(frozen=True)
class Unknown:
    """A value with a tag the codec does not interpret, kept byte for byte."""

    tag: int
    raw: bytes


Value = int | bool | str | bytes | Resolution | Range | Collection | OutOfBand | Unknown


@dataclass
class Attr:
    """One attribute: name, wire tag of its first value, values."""

    name: str
    tag: Tag | int
    values: list[Value]
    value_tags: list[int] = field(default_factory=list, compare=False, repr=False)


@dataclass
class Group:
    """An attribute group (RFC 8010 3.3). ``tag`` is an ``int`` for unassigned delimiters."""

    tag: Tag | int
    attrs: list[Attr]


@dataclass
class Message:
    """An IPP request or response. ``code`` is the operation-id or the status-code."""

    version: tuple[int, int]
    code: int
    request_id: int
    groups: list[Group]

    def attrs(self, group: Tag) -> dict[str, list[Value]]:
        """Attributes of the first group with tag ``group``; a repeated name keeps its first."""
        for g in self.groups:
            if g.tag == group:
                out: dict[str, list[Value]] = {}
                for a in g.attrs:
                    out.setdefault(a.name, a.values)
                return out
        return {}


# RFC 8011 section 5.4.15 / Appendix B (operation-id values used by the hub).
OPERATIONS: dict[str, int] = {
    "Print-Job": 0x0002,
    "Validate-Job": 0x0004,
    "Cancel-Job": 0x0008,
    "Get-Job-Attributes": 0x0009,
    "Get-Jobs": 0x000A,
    "Get-Printer-Attributes": 0x000B,
}

# status-code names: RFC 8011 Appendix B, RFC 3380, RFC 3995, RFC 3998, PWG 5100.7,
# 5100.13, 5100.16, 5100.18, as listed in the IANA IPP registry. 0x0416 and 0x0417
# are reserved there and therefore absent.
STATUS_NAMES: dict[int, str] = {
    0x0000: "successful-ok",
    0x0001: "successful-ok-ignored-or-substituted-attributes",
    0x0002: "successful-ok-conflicting-attributes",
    0x0400: "client-error-bad-request",
    0x0401: "client-error-forbidden",
    0x0402: "client-error-not-authenticated",
    0x0403: "client-error-not-authorized",
    0x0404: "client-error-not-possible",
    0x0405: "client-error-timeout",
    0x0406: "client-error-not-found",
    0x0407: "client-error-gone",
    0x0408: "client-error-request-entity-too-large",
    0x0409: "client-error-request-value-too-long",
    0x040A: "client-error-document-format-not-supported",
    0x040B: "client-error-attributes-or-values-not-supported",
    0x040C: "client-error-uri-scheme-not-supported",
    0x040D: "client-error-charset-not-supported",
    0x040E: "client-error-conflicting-attributes",
    0x040F: "client-error-compression-not-supported",
    0x0410: "client-error-compression-error",
    0x0411: "client-error-document-format-error",
    0x0412: "client-error-document-access-error",
    0x0413: "client-error-attributes-not-settable",
    0x0414: "client-error-ignored-all-subscriptions",
    0x0415: "client-error-too-many-subscriptions",
    0x0418: "client-error-document-password-error",
    0x0419: "client-error-document-permission-error",
    0x041A: "client-error-document-security-error",
    0x041B: "client-error-document-unprintable-error",
    0x041C: "client-error-account-info-needed",
    0x041D: "client-error-account-closed",
    0x041E: "client-error-account-limit-reached",
    0x041F: "client-error-account-authorization-failed",
    0x0420: "client-error-not-fetchable",
    0x0500: "server-error-internal-error",
    0x0501: "server-error-operation-not-supported",
    0x0502: "server-error-service-unavailable",
    0x0503: "server-error-version-not-supported",
    0x0504: "server-error-device-error",
    0x0505: "server-error-temporary-error",
    0x0506: "server-error-not-accepting-jobs",
    0x0507: "server-error-busy",
    0x0508: "server-error-job-canceled",
    0x0509: "server-error-multiple-document-jobs-not-supported",
    0x050A: "server-error-printer-is-deactivated",
    0x050B: "server-error-too-many-jobs",
    0x050C: "server-error-too-many-documents",
}

_KNOWN_GROUPS = {Tag.OPERATION, Tag.JOB, Tag.PRINTER, Tag.UNSUPPORTED}
_OUT_OF_BAND = {Tag.UNSUPPORTED_VALUE, Tag.UNKNOWN, Tag.NO_VALUE}
_INT_TAGS = {Tag.INTEGER, Tag.ENUM}
_BYTES_TAGS = {Tag.OCTET_STRING, Tag.DATETIME}
_LANG_TAGS = {Tag.TEXT_LANG, Tag.NAME_LANG}
_STR_TAGS = {
    Tag.TEXT,
    Tag.NAME,
    Tag.KEYWORD,
    Tag.URI,
    Tag.URI_SCHEME,
    Tag.CHARSET,
    Tag.LANGUAGE,
    Tag.MIME,
} | _LANG_TAGS
_STRUCTURAL = {Tag.BEG_COLLECTION, Tag.END_COLLECTION, Tag.MEMBER_NAME}
_FIXED_LENGTH = {Tag.INTEGER: 4, Tag.ENUM: 4, Tag.BOOLEAN: 1, Tag.DATETIME: 11}
_FIXED_LENGTH.update({Tag.RESOLUTION: 9, Tag.RANGE: 8})
_KNOWN_VALUE_TAGS = (_OUT_OF_BAND | _INT_TAGS | _BYTES_TAGS | _STR_TAGS | _STRUCTURAL) | {
    Tag.BOOLEAN,
    Tag.RESOLUTION,
    Tag.RANGE,
}


# --------------------------------------------------------------------------- decode


class _Reader:
    """Forward-only cursor over the input with bounds checks on every read."""

    __slots__ = ("attributes", "data", "pos", "values")

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0
        self.attributes = 0
        self.values = 0

    def at_end(self) -> bool:
        return self.pos >= len(self.data)

    def take(self, n: int) -> bytes:
        end = self.pos + n
        if end > len(self.data):
            raise IppDecodeError("truncated", f"need {n} bytes at offset {self.pos}")
        chunk = self.data[self.pos : end]
        self.pos = end
        return chunk

    def peek(self) -> int:
        return self.data[self.pos]

    def byte(self) -> int:
        return self.take(1)[0]

    def length(self) -> int:
        value = int.from_bytes(self.take(2), "big", signed=True)
        if value < 0:
            raise IppDecodeError("negative_length", f"at offset {self.pos - 2}")
        return value

    def field(self) -> tuple[int, bytes, bytes]:
        """tag, name, value of one attribute-with-one-value / additional-value (3.1.4/3.1.5)."""
        tag = self.byte()
        name = self.take(self.length())
        value = self.take(self.length())
        return tag, name, value

    def count_value(self) -> None:
        self.values += 1
        if self.values > MAX_TOTAL_VALUES:
            raise IppDecodeError("too_many_values", f"more than {MAX_TOTAL_VALUES} in message")

    def count_attribute(self) -> None:
        self.attributes += 1
        if self.attributes > MAX_ATTRIBUTES:
            raise IppDecodeError("too_many_attributes", f"more than {MAX_ATTRIBUTES}")


def _text(raw: bytes) -> str:
    return raw.decode("utf-8", errors="replace")


def _with_language(raw: bytes) -> str:
    """textWithLanguage / nameWithLanguage (RFC 8010 3.9, Table 7): returns the text."""
    if len(raw) < 2:
        raise IppDecodeError("bad_with_language", "too short")
    lang_len = int.from_bytes(raw[0:2], "big", signed=True)
    if lang_len < 0 or 2 + lang_len + 2 > len(raw):
        raise IppDecodeError("bad_with_language", "language length")
    at = 2 + lang_len
    text_len = int.from_bytes(raw[at : at + 2], "big", signed=True)
    if text_len < 0 or at + 2 + text_len != len(raw):
        raise IppDecodeError("bad_with_language", "text length")
    return _text(raw[at + 2 :])


def _scalar(tag: int, raw: bytes) -> Value:
    """Decode one non-collection value of wire tag ``tag``."""
    if tag not in _KNOWN_VALUE_TAGS:
        return Unknown(tag, bytes(raw))
    expected = _FIXED_LENGTH.get(Tag(tag))
    if expected is not None and len(raw) != expected:
        raise IppDecodeError("bad_value_length", f"tag 0x{tag:02x} with length {len(raw)}")
    if tag in _OUT_OF_BAND:
        if raw:
            raise IppDecodeError("out_of_band_length", f"tag 0x{tag:02x}")
        return OutOfBand(tag)
    if tag in _INT_TAGS:
        return int.from_bytes(raw, "big", signed=True)
    if tag == Tag.BOOLEAN:
        if raw[0] > 1:
            raise IppDecodeError("bad_boolean", f"value {raw[0]}")
        return raw[0] == 1
    if tag in _BYTES_TAGS:
        return bytes(raw)
    if tag == Tag.RESOLUTION:
        return Resolution(
            int.from_bytes(raw[0:4], "big", signed=True),
            int.from_bytes(raw[4:8], "big", signed=True),
            int.from_bytes(raw[8:9], "big", signed=True),
        )
    if tag == Tag.RANGE:
        return Range(
            int.from_bytes(raw[0:4], "big", signed=True),
            int.from_bytes(raw[4:8], "big", signed=True),
        )
    if tag in _LANG_TAGS:
        return _with_language(raw)
    if tag in _STRUCTURAL:  # pragma: no cover - callers consume structural tags first
        raise IppDecodeError("unexpected_structural_tag", f"tag 0x{tag:02x}")
    return _text(raw)


def _value(reader: _Reader, tag: int, raw: bytes, depth: int) -> Value:
    """A value whose header was just read; collections consume their members."""
    reader.count_value()
    if tag == Tag.BEG_COLLECTION:
        # The value-length of begCollection is 0 (3.1.6); bytes in it carry no meaning.
        return _collection(reader, depth + 1)
    return _scalar(tag, raw)


def _collection(reader: _Reader, depth: int) -> Collection:
    """Members up to the matching endCollection (RFC 8010 3.1.6, 3.1.7)."""
    if depth > MAX_DEPTH:
        raise IppDecodeError("depth_exceeded", f"collection nesting over {MAX_DEPTH}")
    members: dict[str, list[Value]] = {}
    member_tags: dict[str, list[int]] = {}
    current: str | None = None
    while True:
        if reader.at_end():
            raise IppDecodeError("truncated", "collection without endCollection")
        if reader.peek() <= 0x0F:
            raise IppDecodeError("unterminated_collection", f"delimiter at offset {reader.pos}")
        tag, name, raw = reader.field()
        if tag == Tag.END_COLLECTION:
            if name or raw:
                raise IppDecodeError("bad_end_collection", "endCollection with a name or value")
            return Collection(members, member_tags)
        if name:
            raise IppDecodeError("member_name_length", f"named value at offset {reader.pos}")
        if tag == Tag.MEMBER_NAME:
            if raw:
                current = _text(raw)
                if current in members:
                    raise IppDecodeError("duplicate_member", "member repeated in collection")
                reader.count_attribute()
                members[current] = []
                member_tags[current] = []
            elif current is None:
                raise IppDecodeError("member_without_name", "empty memberAttrName first")
            # The next field must be a value of this member.
            if reader.at_end():
                raise IppDecodeError("truncated", "memberAttrName without value")
            if reader.peek() in (Tag.END_COLLECTION, Tag.MEMBER_NAME):
                raise IppDecodeError("member_without_value", "memberAttrName without value")
            continue
        if current is None:
            raise IppDecodeError("member_without_name", "member value before memberAttrName")
        values = members[current]
        if len(values) >= MAX_VALUES:
            raise IppDecodeError("too_many_values", f"more than {MAX_VALUES} in a member")
        values.append(_value(reader, tag, raw, depth))
        member_tags[current].append(tag)


def decode(data: bytes | bytearray | memoryview) -> tuple[Message, bytes]:
    """Parse an IPP message; return it and the document data after end-of-attributes."""
    reader = _Reader(bytes(data))
    if len(reader.data) < _HEADER_LENGTH:
        raise IppDecodeError("truncated", "message shorter than the 8-byte header")
    head = reader.take(_HEADER_LENGTH)
    version = (
        int.from_bytes(head[0:1], "big", signed=True),
        int.from_bytes(head[1:2], "big", signed=True),
    )
    code = int.from_bytes(head[2:4], "big", signed=True)
    request_id = int.from_bytes(head[4:8], "big", signed=True)
    groups: list[Group] = []
    group: Group | None = None
    current: Attr | None = None
    while True:
        if reader.at_end():
            raise IppDecodeError("missing_end_tag", "no end-of-attributes-tag")
        tag = reader.peek()
        if tag <= 0x0F:  # delimiter tag (RFC 8010 3.5.1)
            reader.pos += 1
            if tag == Tag.END:
                break
            if tag == 0x00:
                raise IppDecodeError("reserved_tag", "delimiter tag 0x00")
            if len(groups) >= MAX_GROUPS:
                raise IppDecodeError("too_many_groups", f"more than {MAX_GROUPS}")
            group = Group(Tag(tag) if tag in _KNOWN_GROUPS else tag, [])
            groups.append(group)
            current = None
            continue
        if group is None:
            raise IppDecodeError("attribute_outside_group", f"value tag 0x{tag:02x} first")
        tag, name, raw = reader.field()
        if tag == Tag.END_COLLECTION:
            raise IppDecodeError("unexpected_end_collection", "without begCollection")
        if tag == Tag.MEMBER_NAME:
            raise IppDecodeError("unexpected_member_name", "outside a collection")
        if name:
            reader.count_attribute()
            current = Attr(_text(name), Tag(tag) if tag in _KNOWN_VALUE_TAGS else tag, [])
            group.attrs.append(current)
        elif current is None:
            raise IppDecodeError("additional_value_without_attribute", "empty name first")
        elif len(current.values) >= MAX_VALUES:
            raise IppDecodeError("too_many_values", f"more than {MAX_VALUES} in one attribute")
        current.values.append(_value(reader, tag, raw, 0))
        current.value_tags.append(tag)
    document = reader.data[reader.pos :]
    return Message(version, code, request_id, groups), document


# --------------------------------------------------------------------------- encode


def _fits(tag: int, value: Value) -> bool:
    """Whether a plain Python value can be written under wire tag ``tag``."""
    if isinstance(value, bool):
        return tag == Tag.BOOLEAN
    if isinstance(value, int):
        return tag in _INT_TAGS
    if isinstance(value, str):
        return tag in _STR_TAGS
    if isinstance(value, bytes):
        return tag in _BYTES_TAGS
    if isinstance(value, Resolution):
        return tag == Tag.RESOLUTION
    if isinstance(value, Range):
        return tag == Tag.RANGE
    return isinstance(value, Collection) and tag == Tag.BEG_COLLECTION


def _inferred(value: Value) -> int:
    if isinstance(value, bool):
        return Tag.BOOLEAN
    if isinstance(value, int):
        return Tag.INTEGER
    if isinstance(value, str):
        return Tag.KEYWORD
    if isinstance(value, bytes):
        return Tag.OCTET_STRING
    if isinstance(value, Resolution):
        return Tag.RESOLUTION
    if isinstance(value, Range):
        return Tag.RANGE
    if isinstance(value, Collection):
        return Tag.BEG_COLLECTION
    raise IppEncodeError(f"cannot encode value of type {type(value).__name__}")


def _choose_tag(value: Value, recorded: int | None, declared: int | None) -> int:
    if isinstance(value, OutOfBand | Unknown):
        return value.tag
    for candidate in (recorded, declared):
        if candidate is not None and _fits(candidate, value):
            return candidate
    return _inferred(value)


def _length(n: int, what: str) -> bytes:
    if n > _MAX_LENGTH:
        raise IppEncodeError(f"{what} length {n} over {_MAX_LENGTH}")
    return n.to_bytes(2, "big")


def _int32(n: int) -> bytes:
    try:
        return n.to_bytes(4, "big", signed=True)
    except OverflowError as exc:
        raise IppEncodeError(f"integer {n} out of SIGNED-INTEGER range") from exc


class _Writer:
    def __init__(self, language: str) -> None:
        self.out = bytearray()
        self.language = language.encode("utf-8")

    def field(self, tag: int, name: bytes, value: bytes) -> None:
        self.out.append(tag)
        self.out += _length(len(name), "name")
        self.out += name
        self.out += _length(len(value), "value")
        self.out += value

    def scalar(self, tag: int, value: Value) -> bytes:
        if isinstance(value, OutOfBand):
            if not 0x10 <= tag <= 0x1F:
                raise IppEncodeError(f"out-of-band tag 0x{tag:02x} not in 0x10-0x1f")
            return b""
        if isinstance(value, Unknown):
            if not 0x10 <= tag <= 0xFF or tag in _STRUCTURAL:
                raise IppEncodeError(f"Unknown value with structural or delimiter tag 0x{tag:x}")
            return value.raw
        if isinstance(value, bool):
            return b"\x01" if value else b"\x00"
        if isinstance(value, int):
            return _int32(value)
        if isinstance(value, bytes):
            if tag == Tag.DATETIME and len(value) != 11:
                raise IppEncodeError("dateTime must be 11 octets")
            return value
        if isinstance(value, Resolution):
            try:
                units = value.units.to_bytes(1, "big", signed=True)
            except OverflowError as exc:
                raise IppEncodeError(f"resolution units {value.units} out of range") from exc
            return _int32(value.x) + _int32(value.y) + units
        if isinstance(value, Range):
            return _int32(value.lower) + _int32(value.upper)
        if isinstance(value, str):
            text = value.encode("utf-8")
            if tag in _LANG_TAGS:
                return (
                    _length(len(self.language), "language")
                    + self.language
                    + _length(len(text), "text")
                    + text
                )
            return text
        raise IppEncodeError(f"cannot encode value of type {type(value).__name__}")

    def value(self, tag: int, name: bytes, value: Value, depth: int) -> None:
        if isinstance(value, Collection):
            self.field(tag, name, b"")
            self.collection(value, depth + 1)
        else:
            self.field(tag, name, self.scalar(tag, value))

    def collection(self, coll: Collection, depth: int) -> None:
        if depth > MAX_DEPTH:
            raise IppEncodeError(f"collection nesting over {MAX_DEPTH}")
        for member, values in coll.members.items():
            if not member:
                raise IppEncodeError("empty collection member name")
            if not values:
                raise IppEncodeError(f"collection member {member!r} without values")
            self.field(Tag.MEMBER_NAME, b"", member.encode("utf-8"))
            recorded = coll.member_tags.get(member, [])
            for i, v in enumerate(values):
                tag = _choose_tag(v, recorded[i] if len(recorded) == len(values) else None, None)
                self.value(tag, b"", v, depth)
        self.field(Tag.END_COLLECTION, b"", b"")


def _message_language(msg: Message) -> str:
    for value in msg.attrs(Tag.OPERATION).get("attributes-natural-language", []):
        if isinstance(value, str) and value:
            return value
    return "en"


def encode(msg: Message, document: bytes = b"") -> bytes:
    """Serialise ``msg`` (RFC 8010 3.1) followed by ``document`` as the data field."""
    writer = _Writer(_message_language(msg))
    try:
        writer.out += msg.version[0].to_bytes(1, "big", signed=True)
        writer.out += msg.version[1].to_bytes(1, "big", signed=True)
        writer.out += msg.code.to_bytes(2, "big", signed=True)
        writer.out += msg.request_id.to_bytes(4, "big", signed=True)
    except OverflowError as exc:
        raise IppEncodeError("header field out of range") from exc
    for group in msg.groups:
        if not 0x01 <= group.tag <= 0x0F or group.tag == Tag.END:
            raise IppEncodeError(f"group tag 0x{group.tag:x} is not a begin-attribute-group-tag")
        writer.out.append(group.tag)
        for attr in group.attrs:
            if not attr.name:
                raise IppEncodeError("attribute without a name")
            if not attr.values:
                raise IppEncodeError(f"attribute {attr.name!r} without values")
            recorded = attr.value_tags if len(attr.value_tags) == len(attr.values) else []
            name = attr.name.encode("utf-8")
            for i, value in enumerate(attr.values):
                tag = _choose_tag(value, recorded[i] if recorded else None, attr.tag)
                writer.value(tag, name if i == 0 else b"", value, 0)
    writer.out.append(Tag.END)
    writer.out += document
    return bytes(writer.out)
