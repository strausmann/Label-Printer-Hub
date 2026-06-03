"""Tests for F3 — friendly startup error when Settings validation fails.

When a required env var is misconfigured (e.g. PRINTER_HUB_WEBHOOK_API_KEY
too short), the application must exit with code 78 (EX_CONFIG) and print a
human-readable message instead of dumping a raw Pydantic ValidationError
traceback.

These tests use subprocess so they exercise the actual import/startup path
that uvicorn would invoke, not a monkeypatched in-process call.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]

# The Python interpreter from the venv that has all deps installed.
_PYTHON = sys.executable


def _run_import(
    env_overrides: dict[str, str],
    tmp_path: Path,
) -> subprocess.CompletedProcess[str]:
    """Run `python -c 'import app.main'` in a hermetic environment.

    The subprocess runs in ``tmp_path`` (not BACKEND_DIR) so that
    pydantic-settings cannot auto-load a developer's ``backend/.env`` file.
    PYTHONPATH is set to BACKEND_DIR so that ``import app.main`` still
    resolves correctly.

    Only the overrides + minimal PATH are passed so test isolation is
    strict and no local .env can interfere.
    """
    # Phase 1i CA-1: PRINTER_HUB_PRINTERS_CONFIG statt entfernte Printer-Felder.
    # Ein nicht-existierender Pfad ist OK für den Import-Check — Settings-Validierung
    # schlägt nicht fehl weil printers_config nur ein String ist (keine Datei-Existenz-Prüfung).
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "PYTHONPATH": str(BACKEND_DIR),
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
    """A too-short PRINTER_HUB_WEBHOOK_API_KEY must exit 78, not crash with traceback.

    Finding F3: without the fix, a raw Pydantic ValidationError stacktrace
    would be printed and the process would exit with code 1 (unhandled
    exception). With the fix, exit code must be 78 (EX_CONFIG).
    """
    result = _run_import({"PRINTER_HUB_WEBHOOK_API_KEY": "too-short"}, tmp_path)
    assert result.returncode == 78, (
        f"Expected exit code 78 (EX_CONFIG) for misconfigured settings, "
        f"got {result.returncode}.\nstderr:\n{result.stderr}"
    )


def test_short_webhook_key_prints_friendly_message(tmp_path: Path) -> None:
    """Stderr must contain a human-readable error, not a raw traceback.

    The message must mention the env var name so operators know what to fix.
    It must NOT contain 'Traceback' (the raw exception dump).
    """
    result = _run_import({"PRINTER_HUB_WEBHOOK_API_KEY": "too-short"}, tmp_path)
    stderr = result.stderr
    assert "PRINTER_HUB_WEBHOOK_API_KEY" in stderr, (
        f"Friendly error must name the offending env var. Got:\n{stderr}"
    )
    assert "Traceback" not in stderr, (
        f"Raw traceback must not appear in normal mode. Got:\n{stderr}"
    )


def test_short_webhook_key_stderr_mentions_env_example(tmp_path: Path) -> None:
    """Stderr hint must mention .env.example so operators know where to look."""
    result = _run_import({"PRINTER_HUB_WEBHOOK_API_KEY": "too-short"}, tmp_path)
    assert ".env.example" in result.stderr, (
        f"Hint about .env.example missing. Got:\n{result.stderr}"
    )


def test_valid_settings_exits_zero(tmp_path: Path) -> None:
    """Valid settings must not trigger the error handler — import succeeds (exit 0)."""
    result = _run_import(
        {
            "PRINTER_HUB_WEBHOOK_API_KEY": "valid-key-that-is-32-chars-or-more-here",
        },
        tmp_path,
    )
    assert result.returncode == 0, (
        f"Valid settings must allow import to succeed.\n"
        f"stderr:\n{result.stderr}\nstdout:\n{result.stdout}"
    )
