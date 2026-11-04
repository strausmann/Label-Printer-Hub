"""The shipped ``examples/compose*.yml`` files must start a hub that boots.

Since Task 1 the backend refuses to start without ``PRINTER_HUB_SECRET_KEY`` and
``PRINTER_HUB_PUBLIC_URL``; since Task 4 proxy headers only count with
``PRINTER_HUB_SSO_TRUST_TOKEN`` (D10). A compose example missing one of them
is a crash-looping container for whoever copies it. Task 16 extends this file.

This reads YAML text and checks declarations. It cannot prove that compose
accepts the file; that was checked once by hand with ``docker compose config``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

EXAMPLES = Path(__file__).resolve().parents[3] / "examples"
COMPOSE_FILES = sorted(EXAMPLES.glob("compose*.yml"))

PRIVATE_IP = re.compile(
    r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
    r"|192\.168\.\d{1,3}\.\d{1,3}"
    r"|100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3})\b"
)
# Hostnames that appear as URL hosts or Host(`...`) rules; ${VAR} hosts are fine.
HOST = re.compile(r"(?:https?://|Host\(`)([^/\s:`'\"$}),]+)")
ALLOWED_HOSTS = {"localhost", "github.com", "example.invalid"}


def _env_names(service: dict) -> set[str]:
    env = service.get("environment") or {}
    if isinstance(env, dict):
        return set(env)
    return {str(item).split("=", 1)[0] for item in env}


def _backend_env(path: Path) -> set[str]:
    data = yaml.safe_load(path.read_text())
    return _env_names(data["services"]["backend"])


def test_examples_are_found() -> None:
    names = {p.name for p in COMPOSE_FILES}
    assert names >= {
        "compose.standalone.yml",
        "compose.traefik.yml",
        "compose.caddy.yml",
        "compose.pangolin.yml",
        "compose.backend-only.yml",
    }


@pytest.mark.parametrize("path", COMPOSE_FILES, ids=lambda p: p.name)
@pytest.mark.parametrize("name", ["PRINTER_HUB_SECRET_KEY", "PRINTER_HUB_PUBLIC_URL"])
def test_backend_sets_required_settings(path: Path, name: str) -> None:
    assert name in _backend_env(path), f"{path.name}: backend does not set {name}"


@pytest.mark.parametrize("path", COMPOSE_FILES, ids=lambda p: p.name)
def test_required_settings_fail_at_compose_time_when_unset(path: Path) -> None:
    text = path.read_text()
    for name in ("PRINTER_HUB_SECRET_KEY", "PRINTER_HUB_PUBLIC_URL"):
        assert "${" + name + ":?" in text, f"{path.name}: {name} must use the ':?' form"


def test_pangolin_example_passes_the_sso_trust_token() -> None:
    path = EXAMPLES / "compose.pangolin.yml"
    assert "PRINTER_HUB_SSO_TRUST_TOKEN" in _backend_env(path)
    text = path.read_text()
    assert "${PRINTER_HUB_SSO_TRUST_TOKEN:?" in text
    assert "X-Pangolin-Token" in text
    # ``headers`` is a deprecated alias of ``request-headers`` in Pangolin's blueprint schema.
    assert ".request-headers[0].name=X-Pangolin-Token" in text
    assert ".request-headers[0].value=${PRINTER_HUB_SSO_TRUST_TOKEN}" in text
    assert ".headers[" not in text.replace(".request-headers[", "")
    assert "PRINTER_HUB_TRUST_LEGACY_PANGOLIN_USER" in text
    assert "PRINTER_HUB_TRUST_PANGOLIN_BASIC_BYPASS" in text


def test_env_example_lists_required_settings() -> None:
    lines = (EXAMPLES / ".env.example").read_text().splitlines()
    names = {line.split("=", 1)[0] for line in lines if "=" in line and not line.startswith("#")}
    assert {"PRINTER_HUB_SECRET_KEY", "PRINTER_HUB_PUBLIC_URL"} <= names


@pytest.mark.parametrize("path", COMPOSE_FILES, ids=lambda p: p.name)
def test_no_private_addresses_or_real_domains(path: Path) -> None:
    text = path.read_text()
    assert not PRIVATE_IP.search(text), f"{path.name}: private IP address"
    for host in HOST.findall(text):
        if "." not in host:  # docker service names such as "backend"
            continue
        assert host in ALLOWED_HOSTS or host.endswith(".example.invalid"), (
            f"{path.name}: host {host!r} is not example.invalid"
        )
