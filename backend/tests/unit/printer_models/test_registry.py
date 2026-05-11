from __future__ import annotations

from typing import ClassVar

import pytest
from app.printer_models.registry import ModelNotFoundError, ModelRegistry


class FakePtModel:
    model_id = "PT-P750W"
    pjl_signatures: ClassVar[list[str]] = ["MDL:PT-P750W"]
    snmp_model_oid_value_substr = "PT-P750W"
    dpi = (180, 180)
    print_head_pins = 128


def test_registry_register_and_find_by_pjl() -> None:
    fake = FakePtModel()
    ModelRegistry.register(fake)
    pjl = "MFG:Brother;CMD:PJL;MDL:PT-P750W;CLS:PRINTER;"
    assert ModelRegistry.find_by_pjl(pjl) is fake


def test_registry_find_by_snmp_oid_value() -> None:
    fake = FakePtModel()
    ModelRegistry.register(fake)
    oid_value = "Brother PT-P750W"
    assert ModelRegistry.find_by_snmp_oid_value(oid_value) is fake


def test_registry_unknown_pjl_raises() -> None:
    with pytest.raises(ModelNotFoundError):
        ModelRegistry.find_by_pjl("MDL:UnknownModel;")


def test_registry_unknown_snmp_raises() -> None:
    with pytest.raises(ModelNotFoundError):
        ModelRegistry.find_by_snmp_oid_value("Unknown printer")


def test_registry_all_returns_copy() -> None:
    fake = FakePtModel()
    ModelRegistry.register(fake)
    snapshot = ModelRegistry.all()
    snapshot.clear()  # mutating the copy must not affect the registry
    assert len(ModelRegistry.all()) == 1
