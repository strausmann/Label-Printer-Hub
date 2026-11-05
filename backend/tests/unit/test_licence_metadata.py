"""The project's own licence is stated the same way everywhere it is stated."""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SPDX = "AGPL-3.0-or-later"
# The verbatim https://www.gnu.org/licenses/agpl-3.0.txt, 661 lines.
AGPL_TEXT_SHA256 = "0d96a4ff68ad6d4b6f1f30f713b18d5184912ba8dd389f86aa7710db079abcb0"


def _read(relative: str) -> str:
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


def test_license_file_is_agpl() -> None:
    raw = (REPO_ROOT / "LICENSE").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == AGPL_TEXT_SHA256
    assert len(raw.decode("utf-8").splitlines()) == 661


def test_package_metadata() -> None:
    project = tomllib.loads(_read("backend/pyproject.toml"))["project"]
    assert project["license"] == SPDX
    # A leftover classifier would contradict the expression.
    assert not [c for c in project.get("classifiers", []) if c.startswith("License ::")]
    for manifest in ("package.json", "frontend/package.json"):
        assert json.loads(_read(manifest))["license"] == SPDX, manifest


def test_image_labels_and_licence_file() -> None:
    dockerfile = _read("backend/Dockerfile")
    assert f'org.opencontainers.image.licenses="{SPDX}"' in dockerfile
    assert "COPY --chown=hub:hub LICENSE /opt/app/LICENSE" in dockerfile
    assert "COPY --chown=hub:hub LICENSE /opt/app/web/licenses/agpl-3.0.txt" in dockerfile
    workflow = _read(".github/workflows/docker-publish.yml")
    assert workflow.count(f"licenses={SPDX}") == 2
    assert "licenses=MIT" not in workflow


def test_readme_states_licence_history() -> None:
    readme = _read("README.md")
    assert SPDX in readme
    assert re.search(
        r"Releases up to and including \d+\.\d+\.\d+ are MIT; "
        r"from 1\.1\.0 on AGPL-3\.0-or-later",
        readme,
    )
    assert "HUB_REPO_URL" in readme
    trademarks = _read("docs/policies/trademarks.md")
    for name, text in (("README.md", readme), ("trademarks.md", trademarks)):
        assert "fair use" not in text.lower(), name
        assert "MIT license" not in text, name
