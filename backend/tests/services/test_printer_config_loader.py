from __future__ import annotations

from pathlib import Path

import pytest
from app.schemas.printer_config import PrinterYAMLConfig
from app.services.printer_config_loader import PrinterConfigLoader
from pydantic import ValidationError

VALID_YAML = """
schema_version: 1
printers:
  - slug: brother-p750w
    name: "Brother P-750W"
    backend: ptouch
    model: PT-P750W
    host: 172.16.50.212
    port: 9100
"""


def test_load_file_populates_cache(tmp_path: Path):
    cfg_file = tmp_path / "printers.yaml"
    cfg_file.write_text(VALID_YAML)
    PrinterConfigLoader.load_file(cfg_file)
    assert isinstance(PrinterConfigLoader.get("brother-p750w"), PrinterYAMLConfig)
    assert len(PrinterConfigLoader.all()) == 1


def test_invalid_yaml_raises(tmp_path: Path):
    cfg_file = tmp_path / "bad.yaml"
    cfg_file.write_text("schema_version: 1\nprinters:\n  - slug: A-B-C\n")  # uppercase slug
    with pytest.raises(ValidationError):
        PrinterConfigLoader.load_file(cfg_file)


def test_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        PrinterConfigLoader.load_file(tmp_path / "nonexistent.yaml")


def test_reload_replaces_cache(tmp_path: Path):
    cfg_file = tmp_path / "printers.yaml"
    cfg_file.write_text(VALID_YAML)
    PrinterConfigLoader.load_file(cfg_file)
    assert PrinterConfigLoader.get("brother-p750w") is not None

    cfg_file.write_text("""
schema_version: 1
printers:
  - slug: only-ql
    name: "QL"
    backend: brother_ql
    model: QL-820NWB
    host: 1.2.3.4
    cut_defaults:
      half_cut: false
      cut_at_end: true
""")
    PrinterConfigLoader.reload_file(cfg_file)
    assert PrinterConfigLoader.get("brother-p750w") is None
    assert PrinterConfigLoader.get("only-ql") is not None
