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


def _run_import(env_overrides: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run `python -c 'import app.main'` in a clean environment.

    Only the overrides + minimal PATH are passed so test isolation is
    strict and no local .env can interfere.
    """
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "PYTHONPATH": str(BACKEND_DIR),
        # Provide valid required settings so only the explicitly broken
        # setting triggers the ValidationError.
        "PRINTER_HUB_PRINTER_BACKEND": "mock",
        "PRINTER_HUB_PRINTER_MODEL": "PT-P750W",
        "PRINTER_HUB_PRINTER_DISCOVER_VIA_SNMP": "false",
        **env_overrides,
    }
    return subprocess.run(
        [_PYTHON, "-c", "import app.main"],
        cwd=str(BACKEND_DIR),
        capture_output=True,
        text=True,
        env=env,
    )


def test_short_webhook_key_exits_78() -> None:
    """A too-short PRINTER_HUB_WEBHOOK_API_KEY must exit 78, not crash with traceback.

    Finding F3: without the fix, a raw Pydantic ValidationError stacktrace
    would be printed and the process would exit with code 1 (unhandled
    exception). With the fix, exit code must be 78 (EX_CONFIG).
    """
    result = _run_import({"PRINTER_HUB_WEBHOOK_API_KEY": "too-short"})
    assert result.returncode == 78, (
        f"Expected exit code 78 (EX_CONFIG) for misconfigured settings, "
        f"got {result.returncode}.\nstderr:\n{result.stderr}"
    )


def test_short_webhook_key_prints_friendly_message() -> None:
    """Stderr must contain a human-readable error, not a raw traceback.

    The message must mention the env var name so operators know what to fix.
    It must NOT contain 'Traceback' (the raw exception dump).
    """
    result = _run_import({"PRINTER_HUB_WEBHOOK_API_KEY": "too-short"})
    stderr = result.stderr
    assert "PRINTER_HUB_WEBHOOK_API_KEY" in stderr, (
        f"Friendly error must name the offending env var. Got:\n{stderr}"
    )
    assert "Traceback" not in stderr, (
        f"Raw traceback must not appear in normal mode. Got:\n{stderr}"
    )


def test_short_webhook_key_stderr_mentions_env_example() -> None:
    """Stderr hint must mention .env.example so operators know where to look."""
    result = _run_import({"PRINTER_HUB_WEBHOOK_API_KEY": "too-short"})
    assert ".env.example" in result.stderr, (
        f"Hint about .env.example missing. Got:\n{result.stderr}"
    )


def test_valid_settings_exits_zero() -> None:
    """Valid settings must not trigger the error handler — import succeeds (exit 0)."""
    result = _run_import(
        {
            "PRINTER_HUB_WEBHOOK_API_KEY": "valid-key-that-is-32-chars-or-more-here",
        }
    )
    assert result.returncode == 0, (
        f"Valid settings must allow import to succeed.\n"
        f"stderr:\n{result.stderr}\nstdout:\n{result.stdout}"
    )
