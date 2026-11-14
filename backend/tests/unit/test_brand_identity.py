"""Labelyard identity of the backend, and the identifiers that deliberately did not change.

The renamed values are what a user sees (command, API title, default display name, source
link, image labels). The compatibility values live in users' data, cookies, clients and
exported files; renaming them would break an upgrade that is meant to be "change the image
line, pull, restart".
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tomllib
from pathlib import Path

import pytest
from app.build_info import CANONICAL_REPO_URL
from app.config import Settings

BACKEND = Path(__file__).resolve().parents[2]
REPO_URL = "https://github.com/strausmann/labelyard"


def test_cli_prog_name() -> None:
    from app import cli

    assert cli._parser().prog == "labelyard"


def test_cli_alias_installed() -> None:
    scripts = tomllib.loads((BACKEND / "pyproject.toml").read_text())["project"]["scripts"]
    assert scripts["labelyard"] == "app.cli:main"
    assert scripts["printer-hub"] == "app.cli:main"


def test_package_name() -> None:
    assert tomllib.loads((BACKEND / "pyproject.toml").read_text())["project"]["name"] == "labelyard"


def test_openapi_title() -> None:
    from app.main import create_app

    info = create_app()._app.openapi()["info"]
    assert info["title"] == "Labelyard API"
    assert info["description"].startswith("REST + SSE API of Labelyard, the self-hosted Label")


def test_display_name_default() -> None:
    from app.settings_store.registry import SETTINGS

    assert SETTINGS["general.display_name"].default == "Labelyard"


def test_default_database_path_unchanged() -> None:
    assert (
        Settings.model_fields["database_url"].default == "sqlite+aiosqlite:////data/printer-hub.db"
    )


def test_compat_identifiers_unchanged() -> None:
    from app.auth import dependencies, sessions
    from app.auth.key_generator import generate_api_key

    assert (sessions._SESSION_COOKIE, sessions._CSRF_COOKIE) == ("lph_session", "lph_csrf")
    assert dependencies._api_key_header.model.name == "X-Label-Hub-Key"
    assert generate_api_key()[0].startswith("lh_")
    seed = json.loads((BACKEND / "app" / "seed" / "sheet_types.json").read_text())
    entries = (
        seed if isinstance(seed, list) else next(v for v in seed.values() if isinstance(v, list))
    )
    assert entries
    assert {e["format"] for e in entries} == {"label-printer-hub.sheet-type"}


def test_source_url() -> None:
    import app.main as main_module

    assert CANONICAL_REPO_URL == REPO_URL
    assert main_module.HUB_REPO_URL == REPO_URL


# --- container image -----------------------------------------------------------------------

DOCKERFILE = BACKEND / "Dockerfile"


def _dockerfile_text() -> str:
    return DOCKERFILE.read_text().replace("\\\n", " ")


def _label(name: str) -> str:
    match = re.search(rf'{re.escape(name)}="([^"]*)"', _dockerfile_text())
    assert match, f"label {name} missing"
    return match.group(1)


def test_image_labels() -> None:
    assert _label("org.opencontainers.image.title") == "Labelyard"
    assert _label("org.opencontainers.image.description").startswith("Labelyard — the self-hosted")
    for name in ("url", "source", "documentation"):
        assert _label(f"org.opencontainers.image.{name}") == REPO_URL
    assert _label("org.opencontainers.image.authors") == "Björn Strausmann <projects@strausmann.ch>"
    assert 'HUB_REPO_URL="https://github.com/strausmann/labelyard"' in _dockerfile_text()


def _start_command() -> str:
    """The shell string of the Dockerfile's exec-form ``CMD ["sh", "-c", "..."]``."""
    match = re.search(r"^CMD (\[.*\])$", _dockerfile_text(), re.MULTILINE)
    assert match, "CMD missing"
    argv = json.loads(match.group(1))
    assert argv[:2] == ["sh", "-c"]
    return argv[2]


def _port_of_start_command(env: dict[str, str]) -> str:
    """Run the real start command with uvicorn replaced by echo and return the --port value."""
    command = _start_command()
    assert command.lstrip().startswith("exec uvicorn app.main:app")
    command = command.replace("exec uvicorn app.main:app", "echo", 1)
    clean = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("LABELYARD_", "PRINTER_HUB_", "PORT"))
    }
    out = subprocess.run(
        ["sh", "-c", command],
        env={**clean, "FORWARDED_ALLOW_IPS": "127.0.0.1", **env},
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    return out[out.index("--port") + 1]


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({}, "8000"),
        ({"PORT": "8100"}, "8100"),
        ({"PRINTER_HUB_SERVER_PORT": "8200", "PORT": "8100"}, "8200"),
        (
            {"LABELYARD_SERVER_PORT": "8123", "PRINTER_HUB_SERVER_PORT": "8200", "PORT": "8100"},
            "8123",
        ),
        ({"LABELYARD_SERVER_PORT": "", "PORT": "8100"}, "8100"),
    ],
)
def test_start_command_honours_the_server_port(env: dict[str, str], expected: str) -> None:
    assert _port_of_start_command(env) == expected


def test_healthcheck_resolves_the_port_like_the_start_command() -> None:
    check = re.search(r"^HEALTHCHECK .*$", _dockerfile_text(), re.MULTILINE)
    assert check
    chain = "${LABELYARD_SERVER_PORT:-${PRINTER_HUB_SERVER_PORT:-${PORT:-8000}}}"
    assert chain in check.group(0)
    assert chain in _start_command()
