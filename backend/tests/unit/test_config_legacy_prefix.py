"""LABELYARD_* is the settings prefix; PRINTER_HUB_* still works as a deprecated fallback.

Every assertion looks at the effect (the resolved ``Settings`` value or the lock state),
not at whether pydantic considers a source present.
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path

import pytest
from app.config import Settings, get_settings
from app.config_legacy import legacy_env_report, warn_legacy_env
from app.security.secret_box import SecretBox
from app.settings_store import SettingsStore
from pydantic import ValidationError

# Readable fake material, derived at runtime (no high-entropy literal in the source).
KEY = base64.urlsafe_b64encode(b"legacy-prefix-test-key-0123456789"[:32]).decode()
URL = "http://new.example.invalid:8000"
OLD_URL = "http://old.example.invalid:8000"


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, clean_settings_env: None):
    """No ambient configuration of either prefix, no .env in the working directory."""
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_new_prefix_read(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LABELYARD_SECRET_KEY", KEY)
    monkeypatch.setenv("LABELYARD_PUBLIC_URL", URL)
    s = Settings()  # type: ignore[call-arg]
    assert str(s.public_url).rstrip("/") == URL
    assert s.secret_key.get_secret_value() == KEY


def test_legacy_prefix_read(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRINTER_HUB_SECRET_KEY", KEY)
    monkeypatch.setenv("PRINTER_HUB_PUBLIC_URL", OLD_URL)
    s = Settings()  # type: ignore[call-arg]
    assert str(s.public_url).rstrip("/") == OLD_URL
    assert s.secret_key.get_secret_value() == KEY
    import os

    report = legacy_env_report(os.environ)
    assert report.used == ["PRINTER_HUB_PUBLIC_URL", "PRINTER_HUB_SECRET_KEY"]
    assert report.shadowed == []


def test_new_prefix_wins_over_legacy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LABELYARD_SECRET_KEY", KEY)
    monkeypatch.setenv("LABELYARD_PUBLIC_URL", URL)
    monkeypatch.setenv("PRINTER_HUB_PUBLIC_URL", OLD_URL)
    s = Settings()  # type: ignore[call-arg]
    assert str(s.public_url).rstrip("/") == URL
    import os

    report = legacy_env_report(os.environ)
    assert report.shadowed == ["PRINTER_HUB_PUBLIC_URL"]
    assert report.used == []


def test_empty_legacy_alone_is_not_a_value(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty legacy variable must not satisfy a required field either."""
    monkeypatch.setenv("LABELYARD_SECRET_KEY", KEY)
    monkeypatch.setenv("PRINTER_HUB_PUBLIC_URL", "")
    with pytest.raises(ValidationError) as err:
        Settings()  # type: ignore[call-arg]
    assert "public_url" in str(err.value)


def test_empty_legacy_alone_keeps_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """`${PRINTER_HUB_LOG_LEVEL:-}` in a compose file must not turn into an invalid value."""
    monkeypatch.setenv("LABELYARD_SECRET_KEY", KEY)
    monkeypatch.setenv("LABELYARD_PUBLIC_URL", URL)
    monkeypatch.setenv("PRINTER_HUB_LOG_LEVEL", "")
    monkeypatch.setenv("PRINTER_HUB_SERVER_PORT", "")
    s = Settings()  # type: ignore[call-arg]
    assert s.log_level == "INFO"
    assert s.server_port == 8000


def test_empty_legacy_dotenv_value_keeps_the_default(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        f"LABELYARD_SECRET_KEY={KEY}\nLABELYARD_PUBLIC_URL={URL}\nPRINTER_HUB_LOG_LEVEL=\n"
    )
    assert Settings().log_level == "INFO"  # type: ignore[call-arg]


def test_legacy_prefix_from_dotenv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        f"PRINTER_HUB_SECRET_KEY={KEY}\nPRINTER_HUB_PUBLIC_URL={OLD_URL}\n"
    )
    s = Settings()  # type: ignore[call-arg]
    assert str(s.public_url).rstrip("/") == OLD_URL
    assert s.secret_key.get_secret_value() == KEY


def test_new_dotenv_wins_over_legacy_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(f"LABELYARD_SECRET_KEY={KEY}\nLABELYARD_PUBLIC_URL={URL}\n")
    monkeypatch.setenv("PRINTER_HUB_PUBLIC_URL", OLD_URL)
    assert str(Settings().public_url).rstrip("/") == URL  # type: ignore[call-arg]


def test_legacy_env_wins_over_new_dotenv_only_when_new_unset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The process environment of the old prefix still beats a legacy .env value."""
    (tmp_path / ".env").write_text(
        f"PRINTER_HUB_SECRET_KEY={KEY}\nPRINTER_HUB_PUBLIC_URL=http://dotenv.example.invalid\n"
    )
    monkeypatch.setenv("PRINTER_HUB_PUBLIC_URL", OLD_URL)
    assert str(Settings().public_url).rstrip("/") == OLD_URL  # type: ignore[call-arg]


def test_legacy_warning_has_no_values(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("PRINTER_HUB_SECRET_KEY", KEY)
    monkeypatch.setenv("PRINTER_HUB_PUBLIC_URL", OLD_URL)
    monkeypatch.setenv("LABELYARD_PUBLIC_URL", URL)
    import os

    logger = logging.getLogger("test.legacy")
    with caplog.at_level(logging.WARNING, logger="test.legacy"):
        warn_legacy_env(legacy_env_report(os.environ), logger)
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert KEY not in text
    assert OLD_URL not in text
    assert "PRINTER_HUB_SECRET_KEY" in text
    assert "PRINTER_HUB_PUBLIC_URL" in text
    assert len(caplog.records) == 2  # one line for "used", one for "shadowed"


def test_no_warning_without_legacy_variables(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("LABELYARD_SECRET_KEY", KEY)
    import os

    with caplog.at_level(logging.WARNING, logger="test.legacy"):
        warn_legacy_env(legacy_env_report(os.environ), logging.getLogger("test.legacy"))
    assert caplog.records == []


def test_report_counts_dotenv_keys() -> None:
    report = legacy_env_report(
        {"LABELYARD_PUBLIC_URL": "x"}, ["PRINTER_HUB_PUBLIC_URL", "PRINTER_HUB_X"]
    )
    assert report.shadowed == ["PRINTER_HUB_PUBLIC_URL"]
    assert report.used == ["PRINTER_HUB_X"]


def _store() -> SettingsStore:
    return SettingsStore(SecretBox(b"test-secret-key-0123456789abcdef"))


def test_legacy_var_locks_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LABELYARD_SECRET_KEY", KEY)
    monkeypatch.setenv("LABELYARD_PUBLIC_URL", URL)
    monkeypatch.setenv("PRINTER_HUB_SNIPEIT_URL", "https://snipeit.example.invalid")
    get_settings.cache_clear()
    store = _store()
    assert store.is_locked("integrations.snipeit.url") is True
    assert store.get("integrations.snipeit.url") == "https://snipeit.example.invalid"


def test_extra_forbid_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unknown variables in the process environment stay ignored (unchanged behaviour)."""
    monkeypatch.setenv("LABELYARD_SECRET_KEY", KEY)
    monkeypatch.setenv("LABELYARD_PUBLIC_URL", URL)
    monkeypatch.setenv("LABELYARD_NO_SUCH_FIELD", "x")
    monkeypatch.setenv("PRINTER_HUB_NO_SUCH_FIELD", "x")
    Settings()  # type: ignore[call-arg]  # must build


def test_dotenv_with_both_prefixes_builds(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        f"LABELYARD_SECRET_KEY={KEY}\nPRINTER_HUB_PUBLIC_URL={OLD_URL}\n"
    )
    s = Settings()  # type: ignore[call-arg]
    assert s.secret_key.get_secret_value() == KEY
    assert str(s.public_url).rstrip("/") == OLD_URL


@pytest.mark.parametrize("prefix", ["LABELYARD_", "PRINTER_HUB_"])
def test_dotenv_unknown_own_prefix_unchanged(tmp_path: Path, prefix: str) -> None:
    """An unknown key with either prefix is rejected, as `PRINTER_HUB_*` was before the rename."""
    (tmp_path / ".env").write_text(
        f"{prefix}SECRET_KEY={KEY}\n{prefix}PUBLIC_URL={URL}\n{prefix}NO_SUCH_FIELD=x\n"
    )
    with pytest.raises(ValidationError) as err:
        Settings()  # type: ignore[call-arg]
    assert "extra_forbidden" in str(err.value)
    assert f"{prefix.lower()}no_such_field" in str(err.value)


# -- empty values count as "not set" for both prefixes ------------------------------------------


def _required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LABELYARD_SECRET_KEY", KEY)
    monkeypatch.setenv("LABELYARD_PUBLIC_URL", URL)


def test_empty_new_env_does_not_hide_legacy_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """`LABELYARD_X: ${LABELYARD_X:-}` next to an old PRINTER_HUB_X must not switch X off."""
    import os

    _required(monkeypatch)
    monkeypatch.setenv("LABELYARD_SNIPEIT_URL", "")
    monkeypatch.setenv("PRINTER_HUB_SNIPEIT_URL", "https://snipeit.example.invalid")
    assert Settings().snipeit_url == "https://snipeit.example.invalid"  # type: ignore[call-arg]
    report = legacy_env_report(os.environ)
    assert report.used == ["PRINTER_HUB_SNIPEIT_URL"]
    assert report.shadowed == []


def test_empty_new_env_does_not_hide_legacy_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    _required(monkeypatch)
    monkeypatch.setenv("LABELYARD_SNIPEIT_URL", "")
    monkeypatch.setenv("PRINTER_HUB_SNIPEIT_URL", "https://snipeit.example.invalid")
    get_settings.cache_clear()
    store = _store()
    assert store.is_locked("integrations.snipeit.url") is True
    assert store.get("integrations.snipeit.url") == "https://snipeit.example.invalid"


def test_empty_new_dotenv_does_not_hide_legacy_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from app.config_legacy import report_from_process

    (tmp_path / ".env").write_text(
        f"LABELYARD_SECRET_KEY={KEY}\nLABELYARD_PUBLIC_URL={URL}\nLABELYARD_SNIPEIT_URL=\n"
    )
    monkeypatch.setenv("PRINTER_HUB_SNIPEIT_URL", "https://snipeit.example.invalid")
    assert Settings().snipeit_url == "https://snipeit.example.invalid"  # type: ignore[call-arg]
    report = report_from_process()
    assert report.used == ["PRINTER_HUB_SNIPEIT_URL"]
    assert report.shadowed == []


def test_empty_new_env_does_not_hide_legacy_dotenv(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _required(monkeypatch)
    (tmp_path / ".env").write_text("PRINTER_HUB_LOG_LEVEL=DEBUG\n")
    monkeypatch.setenv("LABELYARD_LOG_LEVEL", "")
    assert Settings().log_level == "DEBUG"  # type: ignore[call-arg]


def test_empty_required_new_value_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LABELYARD_SECRET_KEY", KEY)
    monkeypatch.setenv("LABELYARD_PUBLIC_URL", "")
    with pytest.raises(ValidationError) as err:
        Settings()  # type: ignore[call-arg]
    assert "public_url" in str(err.value)
