# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tests for F3 — friendly startup error when Settings validation fails.

When a required env var is misconfigured (e.g. LABELYARD_WEBHOOK_API_KEY
too short), the application must exit with code 78 (EX_CONFIG) and print a
human-readable message instead of dumping a raw Pydantic ValidationError
traceback.

These tests use subprocess so they exercise the actual import/startup path
that uvicorn would invoke, not a monkeypatched in-process call.
"""

from __future__ import annotations

import base64
import os
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]

# The Python interpreter from the venv that has all deps installed.
_PYTHON = sys.executable

# Fake key derived from readable text at runtime (no high-entropy literal).
_FAKE_SECRET_KEY = base64.urlsafe_b64encode(b"test-secret-key-0123456789abcdef").decode()


def _run_import(
    env_overrides: dict[str, str],
    tmp_path: Path,
    *,
    required: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run `python -c 'import app.main'` in a hermetic environment.

    The subprocess runs in ``tmp_path`` (not BACKEND_DIR) so that
    pydantic-settings cannot auto-load a developer's ``backend/.env`` file.
    PYTHONPATH is set to BACKEND_DIR so that ``import app.main`` still
    resolves correctly.

    Only the overrides + minimal PATH are passed so test isolation is
    strict and no local .env can interfere.
    """
    # The required settings are passed explicitly so a failure in a test is
    # caused by the override under test, not by a missing required variable.
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "PYTHONPATH": str(BACKEND_DIR),
        **(
            required
            if required is not None
            else {
                "LABELYARD_SECRET_KEY": _FAKE_SECRET_KEY,
                "LABELYARD_PUBLIC_URL": "http://localhost:8000",
            }
        ),
        **env_overrides,
    }
    return subprocess.run(
        [_PYTHON, "-c", "import app.main"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        env=env,
    )


def test_short_webhook_key_exits_78(tmp_path: Path) -> None:
    """A too-short LABELYARD_WEBHOOK_API_KEY must exit 78, not crash with traceback.

    Finding F3: without the fix, a raw Pydantic ValidationError stacktrace
    would be printed and the process would exit with code 1 (unhandled
    exception). With the fix, exit code must be 78 (EX_CONFIG).
    """
    result = _run_import({"LABELYARD_WEBHOOK_API_KEY": "too-short"}, tmp_path)
    assert result.returncode == 78, (
        f"Expected exit code 78 (EX_CONFIG) for misconfigured settings, "
        f"got {result.returncode}.\nstderr:\n{result.stderr}"
    )


def test_short_webhook_key_prints_friendly_message(tmp_path: Path) -> None:
    """Stderr must contain a human-readable error, not a raw traceback.

    The message must mention the env var name so operators know what to fix.
    It must NOT contain 'Traceback' (the raw exception dump).
    """
    result = _run_import({"LABELYARD_WEBHOOK_API_KEY": "too-short"}, tmp_path)
    stderr = result.stderr
    assert "LABELYARD_WEBHOOK_API_KEY" in stderr, (
        f"Friendly error must name the offending env var. Got:\n{stderr}"
    )
    assert "Traceback" not in stderr, (
        f"Raw traceback must not appear in normal mode. Got:\n{stderr}"
    )


def test_short_webhook_key_stderr_mentions_env_example(tmp_path: Path) -> None:
    """Stderr hint must mention .env.example so operators know where to look."""
    result = _run_import({"LABELYARD_WEBHOOK_API_KEY": "too-short"}, tmp_path)
    assert ".env.example" in result.stderr, (
        f"Hint about .env.example missing. Got:\n{result.stderr}"
    )


def test_valid_settings_exits_zero(tmp_path: Path) -> None:
    """Valid settings must not trigger the error handler — import succeeds (exit 0)."""
    result = _run_import(
        {
            "LABELYARD_WEBHOOK_API_KEY": "valid-key-that-is-32-chars-or-more-here",
        },
        tmp_path,
    )
    assert result.returncode == 0, (
        f"Valid settings must allow import to succeed.\n"
        f"stderr:\n{result.stderr}\nstdout:\n{result.stdout}"
    )


_LEGACY_REQUIRED = {
    "PRINTER_HUB_SECRET_KEY": _FAKE_SECRET_KEY,
    "PRINTER_HUB_PUBLIC_URL": "http://localhost:8000",
}


def test_legacy_prefix_only_still_starts(tmp_path: Path) -> None:
    """A deployment that sets only PRINTER_HUB_* keeps booting."""
    result = _run_import({}, tmp_path, required=_LEGACY_REQUIRED)
    assert result.returncode == 0, result.stderr


def test_legacy_prefix_error_message_names_the_new_variable(tmp_path: Path) -> None:
    result = _run_import(
        {"PRINTER_HUB_WEBHOOK_API_KEY": "too-short"}, tmp_path, required=_LEGACY_REQUIRED
    )
    assert result.returncode == 78, result.stderr
    assert "LABELYARD_WEBHOOK_API_KEY" in result.stderr


def test_legacy_log_level_debug_reraises(tmp_path: Path) -> None:
    """PRINTER_HUB_LOG_LEVEL=DEBUG still asks for the raw traceback instead of exit 78."""
    result = _run_import(
        {"PRINTER_HUB_LOG_LEVEL": "DEBUG", "LABELYARD_WEBHOOK_API_KEY": "too-short"}, tmp_path
    )
    assert result.returncode == 1, result.stderr
    assert "Traceback" in result.stderr


# Obviously fake marker, short enough to fail validation, never a real secret.
_MARKER = "marker-secret-must-not-print"


def test_debug_path_never_prints_input_values(tmp_path: Path) -> None:
    """The DEBUG re-raise gives a traceback but must not echo the offending values."""
    result = _run_import(
        {
            "LABELYARD_LOG_LEVEL": "DEBUG",
            "LABELYARD_WEBHOOK_API_KEY": _MARKER,
            "LABELYARD_SECRET_KEY": _MARKER,
        },
        tmp_path,
    )
    assert result.returncode == 1, result.stderr
    assert "Traceback" in result.stderr
    assert "webhook_api_key" in result.stderr  # still tells the operator what is wrong
    assert _MARKER not in result.stderr
    assert _MARKER not in result.stdout


def test_error_names_the_legacy_variable_when_only_that_is_set(tmp_path: Path) -> None:
    result = _run_import(
        {"PRINTER_HUB_WEBHOOK_API_KEY": "too-short"}, tmp_path, required=_LEGACY_REQUIRED
    )
    assert result.returncode == 78, result.stderr
    assert "LABELYARD_WEBHOOK_API_KEY (legacy PRINTER_HUB_WEBHOOK_API_KEY):" in result.stderr, (
        result.stderr
    )


def test_error_names_only_the_new_variable_when_it_is_set(tmp_path: Path) -> None:
    result = _run_import({"LABELYARD_WEBHOOK_API_KEY": "too-short"}, tmp_path)
    assert result.returncode == 78, result.stderr
    assert "LABELYARD_WEBHOOK_API_KEY:" in result.stderr
    assert "legacy" not in result.stderr


def test_unknown_dotenv_key_is_not_double_prefixed(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("LABELYARD_NO_SUCH_FIELD=x\n")
    result = _run_import({}, tmp_path)
    assert result.returncode == 78, result.stderr
    assert "LABELYARD_NO_SUCH_FIELD:" in result.stderr
    assert "LABELYARD_LABELYARD" not in result.stderr
