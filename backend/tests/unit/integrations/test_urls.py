"""Unit tests for the integration base-URL helper."""

from __future__ import annotations

import pytest
from app.integrations.urls import api_url, base_url

HOST = "https://paperless.example.invalid"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (HOST, HOST),
        (HOST + "/", HOST),
        (HOST + "/api", HOST),
        (HOST + "/api/", HOST),
        (HOST + "/paperless", HOST + "/paperless"),
        (HOST + "/paperless/", HOST + "/paperless"),
        (HOST + "/paperless/api/", HOST + "/paperless"),
        ("  " + HOST + "/api/ ", HOST),
        (HOST + "/?x=1#frag", HOST),
        (HOST + "/paperless/api?x=1", HOST + "/paperless"),
        (HOST + ":8000/api", HOST + ":8000"),
        # Only a trailing segment named exactly "api" is dropped.
        (HOST + "/apiary", HOST + "/apiary"),
        (HOST + "/my/api/paperless", HOST + "/my/api/paperless"),
    ],
)
def test_base_url_strip_api(raw: str, expected: str) -> None:
    assert base_url(raw, strip_api=True) == expected


def test_base_url_without_strip_keeps_api_segment() -> None:
    assert base_url(HOST + "/api/", strip_api=False) == HOST + "/api"
    assert base_url(HOST + "/x/?q=1", strip_api=False) == HOST + "/x"


def test_api_url_never_doubles_api() -> None:
    for raw in (HOST, HOST + "/", HOST + "/api", HOST + "/api/"):
        assert api_url(raw, "/api/documents/?page_size=1", strip_api=True) == (
            HOST + "/api/documents/?page_size=1"
        )
    assert api_url(HOST + "/paperless/", "/api/documents/", strip_api=True) == (
        HOST + "/paperless/api/documents/"
    )


@pytest.mark.parametrize("raw", ["http://[::1", "https://[host"])
def test_base_url_raises_value_error_on_malformed_url(raw: str) -> None:
    # Environment-provided URLs bypass the settings validator.
    with pytest.raises(ValueError):
        base_url(raw)
    with pytest.raises(ValueError):
        api_url(raw, "/x")
