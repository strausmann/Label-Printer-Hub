"""``printer_url``: one slash, no credentials, IPv6 hosts bracketed exactly once (#228)."""

from __future__ import annotations

from uuid import UUID

import pytest
from app.services.test_print import printer_url
from pydantic import AnyHttpUrl, TypeAdapter

PID = UUID("11111111-1111-1111-1111-111111111111")


def _url(text: str) -> AnyHttpUrl:
    return TypeAdapter(AnyHttpUrl).validate_python(text)


@pytest.mark.parametrize(
    ("public", "expected_base"),
    [
        ("https://hub.example.invalid", "https://hub.example.invalid"),
        ("https://hub.example.invalid/", "https://hub.example.invalid"),
        ("http://192.0.2.7:8080/", "http://192.0.2.7:8080"),
        ("https://hub.example.invalid:443/base", "https://hub.example.invalid/base"),
        ("https://hub.example.invalid/base/", "https://hub.example.invalid/base"),
        ("http://[::1]/", "http://[::1]"),
        ("http://[::1]:8080/base/", "http://[::1]:8080/base"),
        ("http://[2001:db8::7]:8080", "http://[2001:db8::7]:8080"),
        ("https://u:pw@hub.example.invalid/b?x=1#frag", "https://hub.example.invalid/b"),
        ("http://u:pw@[::1]:81/b/?x=1", "http://[::1]:81/b"),
    ],
)
def test_printer_url(public: str, expected_base: str) -> None:
    url = printer_url(_url(public), PID)
    assert url == f"{expected_base}/printers/{PID}"
    for leak in ("pw", "u:", "x=1", "frag", "[["):
        assert leak not in url
