# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""PDF font override: LABELYARD_PDF_FONT wins, PRINTHUB_PDF_FONT is the deprecated fallback."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from app.page_render import pdf
from app.page_render.pdf import BUNDLED_FONT, resolve_font_path


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pdf, "_legacy_font_warned", False)
    monkeypatch.delenv("LABELYARD_PDF_FONT", raising=False)
    monkeypatch.delenv("PRINTHUB_PDF_FONT", raising=False)


def _font(tmp_path: Path, name: str) -> Path:
    path = tmp_path / name
    path.write_bytes(BUNDLED_FONT.read_bytes())
    return path


def test_new_font_env_wins(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    new, old = _font(tmp_path, "new.ttf"), _font(tmp_path, "old.ttf")
    monkeypatch.setenv("LABELYARD_PDF_FONT", str(new))
    monkeypatch.setenv("PRINTHUB_PDF_FONT", str(old))
    assert resolve_font_path() == new


def test_legacy_font_env_read(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    old = _font(tmp_path, "old.ttf")
    monkeypatch.setenv("PRINTHUB_PDF_FONT", str(old))
    assert resolve_font_path() == old


def test_empty_new_font_env_falls_back_to_legacy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    old = _font(tmp_path, "old.ttf")
    monkeypatch.setenv("LABELYARD_PDF_FONT", "")
    monkeypatch.setenv("PRINTHUB_PDF_FONT", str(old))
    assert resolve_font_path() == old


def test_missing_new_font_names_the_new_variable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from app.page_render.pdf import FontNotFoundError

    monkeypatch.setenv("LABELYARD_PDF_FONT", str(tmp_path / "missing.ttf"))
    with pytest.raises(FontNotFoundError) as err:
        resolve_font_path()
    assert "LABELYARD_PDF_FONT" in str(err.value)


def test_no_override_uses_bundled_font() -> None:
    assert resolve_font_path() == BUNDLED_FONT


def test_legacy_font_env_warns_once_with_the_name_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    old = _font(tmp_path, "secret-dir-marker.ttf")
    monkeypatch.setenv("PRINTHUB_PDF_FONT", str(old))
    with caplog.at_level(logging.WARNING, logger="app.page_render.pdf"):
        resolve_font_path()
        resolve_font_path()
    messages = [r.getMessage() for r in caplog.records]
    assert len(messages) == 1
    assert "PRINTHUB_PDF_FONT" in messages[0]
    assert "LABELYARD_PDF_FONT" in messages[0]
    assert "secret-dir-marker" not in messages[0]


def test_new_font_env_does_not_warn(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("LABELYARD_PDF_FONT", str(_font(tmp_path, "new.ttf")))
    with caplog.at_level(logging.WARNING, logger="app.page_render.pdf"):
        resolve_font_path()
    assert caplog.records == []
