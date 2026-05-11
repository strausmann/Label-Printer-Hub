from __future__ import annotations

from typing import ClassVar

import pytest
from app.models.tape import TapeSpec
from app.printer_models.registry import ModelNotFoundError, ModelRegistry
from app.services.status_block import StatusBlock
from PIL import Image


class FakePtModel:
    model_id = "PT-P750W"
    pjl_signatures: ClassVar[list[str]] = ["MDL:PT-P750W"]
    snmp_model_oid_value_substr = "PT-P750W"
    dpi: ClassVar[tuple[int, int]] = (180, 180)
    print_head_pins = 128

    async def query_status(
        self,
        host: str,
        port: int = 9100,
        timeout_s: float = 5.0,
    ) -> StatusBlock:
        raise NotImplementedError("test double — not exercised")

    def width_to_pixels(self, tape_spec: TapeSpec) -> int:
        raise NotImplementedError("test double — not exercised")

    def build_print_job(
        self,
        image: Image.Image,
        tape_spec: TapeSpec,
        auto_cut: bool = True,
        high_resolution: bool = False,
    ) -> bytes:
        raise NotImplementedError("test double — not exercised")


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
    pjl = "MDL:UnknownModel;"
    with pytest.raises(ModelNotFoundError, match="UnknownModel"):
        ModelRegistry.find_by_pjl(pjl)


def test_registry_unknown_snmp_raises() -> None:
    oid = "Unknown printer"
    with pytest.raises(ModelNotFoundError, match="Unknown printer"):
        ModelRegistry.find_by_snmp_oid_value(oid)


def test_registry_all_returns_copy() -> None:
    fake = FakePtModel()
    ModelRegistry.register(fake)
    snapshot = ModelRegistry.all()
    snapshot.clear()  # mutating the copy must not affect the registry
    assert len(ModelRegistry.all()) == 1


def test_register_rejects_empty_pjl_signature() -> None:
    class BadModel(FakePtModel):
        pjl_signatures: ClassVar[list[str]] = [""]

    with pytest.raises(ValueError, match="empty PJL signature"):
        ModelRegistry.register(BadModel())


def test_register_rejects_empty_snmp_substring() -> None:
    class BadModel(FakePtModel):
        snmp_model_oid_value_substr = ""

    with pytest.raises(ValueError, match="empty SNMP OID substring"):
        ModelRegistry.register(BadModel())
