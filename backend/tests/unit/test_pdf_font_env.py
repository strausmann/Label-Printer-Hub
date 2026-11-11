"""PDF font override: LABELYARD_PDF_FONT wins, PRINTHUB_PDF_FONT is the deprecated fallback."""

from __future__ import annotations

from pathlib import Path

import pytest
from app.page_render.pdf import BUNDLED_FONT, resolve_font_path


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch) -> None:
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
