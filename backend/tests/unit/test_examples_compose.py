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


# --- Task 16: single container (D1), no removed variables, spec 6 e2e coverage -------------

REPO = Path(__file__).resolve().parents[3]
SMOKE = REPO / "dev" / "docker-compose.smoke.yml"
ALL_COMPOSE = [*COMPOSE_FILES, SMOKE]
# Variables of the removed Go frontend and of the retired env-configured printer (spec 7.1, 8).
REMOVED_VARIABLES = (
    "PRINTERS_CONFIG",
    "PRINTER_BACKEND",
    "PRINTER_MODEL",
    "PRINTER_DISCOVER_VIA_SNMP",
    "PRINTER_SNMP_COMMUNITY",
    "PT750W_HOST",
    "PT750W_PORT",
    "BACKEND_URL",
    "CSRF_KEY",
    "FRONTEND_PORT",
)


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


@pytest.mark.parametrize("path", ALL_COMPOSE, ids=lambda p: p.name)
def test_examples_have_no_frontend_service(path: Path) -> None:
    services = _load(path)["services"]
    assert "frontend" not in services, f"{path.name}: the hub is one container (D1)"
    for name, service in services.items():
        image = str(service.get("image", ""))
        assert "label-printer-hub-frontend" not in image, (
            f"{path.name}: {name} uses the frontend image"
        )
        build = service.get("build")
        context = build.get("context", "") if isinstance(build, dict) else str(build or "")
        assert "frontend" not in str(context), f"{path.name}: {name} builds the frontend"


@pytest.mark.parametrize("path", [*COMPOSE_FILES, SMOKE], ids=lambda p: p.name)
def test_examples_do_not_use_removed_variables(path: Path) -> None:
    text = path.read_text()
    for name in REMOVED_VARIABLES:
        assert not re.search(rf"(?<![A-Z_]){name}(?![A-Z_])", text), (
            f"{path.name}: removed variable {name}"
        )


@pytest.mark.parametrize(
    "path", [p for p in COMPOSE_FILES if p.name != "compose.backend-only.yml"], ids=lambda p: p.name
)
def test_example_variables_carry_the_settings_prefix(path: Path) -> None:
    # Unprefixed names (DATABASE_URL, WEBHOOK_API_KEY, ...) are ignored by the backend.
    allowed = {"PORT", "FORWARDED_ALLOW_IPS"}
    for name in _backend_env(path):
        assert name in allowed or name.startswith("PRINTER_HUB_"), (
            f"{path.name}: {name} is not read"
        )


@pytest.mark.parametrize(
    "name", ["compose.traefik.yml", "compose.caddy.yml", "compose.pangolin.yml"]
)
def test_proxy_examples_target_the_backend_on_8000(name: str) -> None:
    text = (EXAMPLES / name).read_text()
    assert "8080" not in text, f"{name}: the UI is served on the backend port, not 8080"
    if name == "compose.traefik.yml":
        assert "loadbalancer.server.port=8000" in text.replace("${BACKEND_PORT:-8000}", "8000")
    if name == "compose.caddy.yml":
        assert "upstreams ${BACKEND_PORT:-8000}" in text or "upstreams 8000" in text
    if name == "compose.pangolin.yml":
        assert "targets[0].port=${BACKEND_PORT:-8000}" in text


def test_standalone_publishes_the_backend_port() -> None:
    backend = _load(EXAMPLES / "compose.standalone.yml")["services"]["backend"]
    assert any(
        str(p).endswith(":8000") or ":" + "${BACKEND_PORT:-8000}" in str(p)
        for p in backend["ports"]
    )


def test_smoke_compose_boots_one_container_with_required_settings() -> None:
    data = _load(SMOKE)
    assert list(data["services"]) == ["backend"]
    env = _env_names(data["services"]["backend"])
    assert {"PRINTER_HUB_SECRET_KEY", "PRINTER_HUB_PUBLIC_URL"} <= env


def test_examples_readme_describes_one_container() -> None:
    text = (EXAMPLES / "README.md").read_text()
    assert "label-printer-hub-frontend" not in text
    assert "Two-container" not in text and "two containers" not in text.lower()


def test_readme_has_no_removed_printer_variables() -> None:
    text = (REPO / "README.md").read_text()
    for name in REMOVED_VARIABLES:
        assert not re.search(rf"PRINTER_HUB_{name}\b", text), f"README.md: removed variable {name}"
    assert "PRINTER_HUB_SECRET_KEY" in text and "PRINTER_HUB_PUBLIC_URL" in text


def test_migration_note_covers_the_breaking_changes() -> None:
    text = (REPO / "docs" / "migration" / "v-next-single-container.md").read_text()
    for needle in (
        "PRINTER_HUB_SECRET_KEY",
        "PRINTER_HUB_PUBLIC_URL",
        "PRINTER_HUB_SSO_TRUST_TOKEN",
        "PRINTER_HUB_TRUST_LEGACY_PANGOLIN_USER",
        "PRINTER_HUB_TRUST_PANGOLIN_BASIC_BYPASS",
        "PRINTER_HUB_PANGOLIN_BYPASS_SCOPE_DOWNGRADE",
        "printer-hub admin create-key",
        "/api/v1/events",
        "label-printer-hub-backend",
        "PRINTERS_CONFIG",
    ):
        assert needle in text, f"migration note does not mention {needle}"


def test_architecture_docs_describe_the_single_process() -> None:
    arch = (REPO / "docs" / "architecture.md").read_text()
    assert "Go web server" not in arch and "oapi-codegen" not in arch
    assert "ADR [0015]" in arch or "0015-single-process-deployment" in arch
    sse = (REPO / "docs" / "architecture" / "sse.md").read_text()
    assert "/api/v1/events" in sse
    assert "backend:8090" not in sse and "HTMX" not in sse


def test_privacy_policy_example_uses_documentation_addresses() -> None:
    text = (REPO / "docs" / "policies" / "privacy.md").read_text()
    text = re.sub(r"\d+\.\d+\.\d+\.\d+/\d+", "", text)  # CIDR ranges name a network, not a host
    assert not PRIVATE_IP.search(text), "privacy.md quotes an address from a real network"


# One e2e spec per row of spec section 6 (page -> spec file and a test title that names it).
SECTION_6_E2E = {
    "overview": ("printers.spec.ts", r"overview answers its three questions"),
    "printer detail": ("printers.spec.ts", r"pausing a printer"),
    "jobs list, detail, retry": ("jobs.spec.ts", r"retry a failed job"),
    "integration item view": ("integrations.spec.ts", r"item view opens"),
    "QR path": ("lookup.spec.ts", r"opening /asset/<id>"),
    "settings: access and keys": ("settings.spec.ts", r"access and keys"),
    "settings: printers": ("settings.spec.ts", r"printers: add, edit and disable"),
    "sign-in": ("shell.spec.ts", r"sign-in rejects a wrong key"),
    "bootstrap": ("shell.spec.ts", r"bootstrap flow creates first admin key"),
}


@pytest.mark.parametrize("page", sorted(SECTION_6_E2E))
def test_every_section_6_page_has_an_e2e_spec(page: str) -> None:
    filename, title = SECTION_6_E2E[page]
    spec = (REPO / "frontend" / "e2e" / filename).read_text()
    assert re.search(r"\btest\(\s*[\"'`][^\"'`]*" + title, spec), (
        f"no e2e test for '{page}' in {filename}"
    )


def test_create_key_instructions_carry_the_required_flags_and_no_log_claim() -> None:
    files = [*COMPOSE_FILES, EXAMPLES / "README.md", REPO / "README.md"]
    files.append(REPO / "docs" / "migration" / "v-next-single-container.md")
    for path in files:
        for line in path.read_text().splitlines():
            if "printer-hub admin create-key" in line and "docker" in line:
                assert "--scope" in line and "--name" in line, f"{path.name}: {line.strip()}"
            assert "printed in the container log" not in line, f"{path.name}: false log claim"


def test_image_ships_third_party_notices() -> None:
    dockerfile = (REPO / "backend" / "Dockerfile").read_text()
    assert "THIRD_PARTY_NOTICES.md" in dockerfile
    notices = (REPO / "THIRD_PARTY_NOTICES.md").read_text()
    for needle in ("cryptography", "greenlet", "OFL-1.1", "zxing"):
        assert needle in notices


@pytest.mark.parametrize("path", COMPOSE_FILES, ids=lambda p: p.name)
def test_forwarded_allow_ips_is_never_a_wildcard(path: Path) -> None:
    """``*`` trusts every peer, so any client could forge X-Forwarded-For (issue #160)."""
    for line in path.read_text().splitlines():
        if "FORWARDED_ALLOW_IPS" in line and not line.lstrip().startswith("#"):
            assert "*" not in line, f"{path.name}: wildcard FORWARDED_ALLOW_IPS: {line.strip()}"


def test_env_example_has_no_wildcard_forwarded_ips() -> None:
    for line in (EXAMPLES / ".env.example").read_text().splitlines():
        if "FORWARDED_ALLOW_IPS=" in line:
            assert "*" not in line.split("=", 1)[1], line


PROXY_EXAMPLES = ["compose.traefik.yml", "compose.caddy.yml", "compose.pangolin.yml"]


def _forwarded_value(path: Path) -> str:
    env = _load(path)["services"]["backend"]["environment"]
    values = [e.split("=", 1)[1] for e in env if str(e).startswith("FORWARDED_ALLOW_IPS=")]
    assert len(values) == 1, f"{path.name}: FORWARDED_ALLOW_IPS must be set exactly once"
    return values[0]


@pytest.mark.parametrize("name", PROXY_EXAMPLES)
def test_proxy_examples_trust_exactly_one_fixed_proxy_address(name: str) -> None:
    """Behind the proxy every client shares its address unless that one peer is trusted (#160).

    The proxy network is external, so the address cannot be declared here; it comes from a
    required PROXY_IP. No wildcard, no loopback, no list, no subnet, no optional default.
    """
    value = _forwarded_value(EXAMPLES / name)
    assert re.fullmatch(r"\$\{PROXY_IP:\?[^}:]+\}", value), f"{name}: {value!r}"
    assert "*" not in value and "127.0.0.1" not in value and "," not in value and "/" not in value


@pytest.mark.parametrize("name", PROXY_EXAMPLES)
def test_proxy_examples_compose_config_needs_a_single_proxy_ip(name: str) -> None:
    import shutil
    import subprocess

    if shutil.which("docker") is None:
        pytest.skip("docker not installed")
    base = {
        "PRINTER_HUB_SECRET_KEY": "x" * 43,
        "PRINTER_HUB_PUBLIC_URL": "https://printerhub.example.invalid",
        "PRINTERHUB_HOST": "printerhub.example.invalid",
        "PRINTER_HUB_SSO_TRUST_TOKEN": "t" * 64,
        "PATH": __import__("os").environ["PATH"],
    }
    cmd = ["docker", "compose", "-f", str(EXAMPLES / name), "config"]
    ok = subprocess.run(
        [*cmd, "--quiet"], env={**base, "PROXY_IP": "192.0.2.10"}, capture_output=True, timeout=60
    )
    assert ok.returncode == 0, ok.stderr.decode()
    missing = subprocess.run(cmd, env=base, capture_output=True, timeout=60)
    assert missing.returncode != 0 and b"PROXY_IP" in missing.stderr
