"""Tests für printer_admin Pydantic-Schemas (Task 2.1).

Testplan:
- SNMPConfig Defaults (discover=False, community="public")
- SNMPConfig discover=True ohne community → ValidationError
- PrinterConnection mit Default-SNMP
- PrinterCreatePayload minimal (alle Defaults greifen)
- Slug-Regex rejects uppercase
- Backend Literal rejects "unknown"
- PrinterUpdatePayload all optional (empty patch valid)
- queue.timeout_s range (0 → fail, 601 → fail)

Test-IPs: 192.0.2.x (RFC 5737 documentation range).
"""

from __future__ import annotations

import pytest
from app.schemas.printer_admin import (
    PrinterConnection,
    PrinterCreatePayload,
    PrinterCutDefaults,
    PrinterQueueSettings,
    PrinterUpdatePayload,
    SNMPConfig,
)
from pydantic import ValidationError

# ---------------------------------------------------------------------------
# SNMPConfig
# ---------------------------------------------------------------------------


class TestSNMPConfig:
    def test_defaults(self) -> None:
        """SNMPConfig ohne Argumente: discover=False, community='public'."""
        cfg = SNMPConfig()
        assert cfg.discover is False
        assert cfg.community == "public"

    def test_explicit_values(self) -> None:
        cfg = SNMPConfig(discover=True, community="private")
        assert cfg.discover is True
        assert cfg.community == "private"

    def test_discover_true_ohne_community_raises(self) -> None:
        """discover=True mit community=None muss ValidationError werfen."""
        with pytest.raises(ValidationError) as exc_info:
            SNMPConfig(discover=True, community=None)
        assert "community" in str(exc_info.value).lower()

    def test_discover_false_community_none_ok(self) -> None:
        """discover=False erlaubt community=None."""
        cfg = SNMPConfig(discover=False, community=None)
        assert cfg.community is None

    def test_community_max_length(self) -> None:
        """community darf maximal 64 Zeichen lang sein."""
        with pytest.raises(ValidationError):
            SNMPConfig(community="x" * 65)

    def test_community_64_chars_ok(self) -> None:
        cfg = SNMPConfig(community="x" * 64)
        assert len(cfg.community) == 64  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# PrinterConnection
# ---------------------------------------------------------------------------


class TestPrinterConnection:
    def test_minimal_with_defaults(self) -> None:
        """PrinterConnection mit Pflichtfeldern — SNMP-Default greift."""
        conn = PrinterConnection(host="192.0.2.1", port=9100)
        assert conn.host == "192.0.2.1"
        assert conn.port == 9100
        assert conn.snmp.discover is False
        assert conn.snmp.community == "public"

    def test_port_min(self) -> None:
        conn = PrinterConnection(host="192.0.2.1", port=1)
        assert conn.port == 1

    def test_port_max(self) -> None:
        conn = PrinterConnection(host="192.0.2.1", port=65535)
        assert conn.port == 65535

    def test_port_zero_rejected(self) -> None:
        with pytest.raises(ValidationError):
            PrinterConnection(host="192.0.2.1", port=0)

    def test_port_too_high_rejected(self) -> None:
        with pytest.raises(ValidationError):
            PrinterConnection(host="192.0.2.1", port=65536)

    def test_host_empty_rejected(self) -> None:
        with pytest.raises(ValidationError):
            PrinterConnection(host="", port=9100)

    def test_custom_snmp(self) -> None:
        conn = PrinterConnection(
            host="192.0.2.2",
            port=161,
            snmp=SNMPConfig(discover=True, community="private"),
        )
        assert conn.snmp.discover is True
        assert conn.snmp.community == "private"


# ---------------------------------------------------------------------------
# PrinterQueueSettings
# ---------------------------------------------------------------------------


class TestPrinterQueueSettings:
    def test_default_timeout(self) -> None:
        q = PrinterQueueSettings()
        assert q.timeout_s == 30

    def test_timeout_min(self) -> None:
        q = PrinterQueueSettings(timeout_s=1)
        assert q.timeout_s == 1

    def test_timeout_max(self) -> None:
        q = PrinterQueueSettings(timeout_s=600)
        assert q.timeout_s == 600

    def test_timeout_zero_rejected(self) -> None:
        with pytest.raises(ValidationError):
            PrinterQueueSettings(timeout_s=0)

    def test_timeout_601_rejected(self) -> None:
        with pytest.raises(ValidationError):
            PrinterQueueSettings(timeout_s=601)


# ---------------------------------------------------------------------------
# PrinterCutDefaults
# ---------------------------------------------------------------------------


class TestPrinterCutDefaults:
    def test_defaults(self) -> None:
        cut = PrinterCutDefaults()
        assert cut.half_cut is False


# ---------------------------------------------------------------------------
# PrinterCreatePayload
# ---------------------------------------------------------------------------


class TestPrinterCreatePayload:
    def _minimal(self, **overrides: object) -> dict[str, object]:
        base: dict[str, object] = {
            "name": "Brother P-750W",
            "slug": "brother-p750w",
            "model": "PT-P750W",
            "backend": "ptouch",
            "connection": {"host": "192.0.2.10", "port": 9100},
        }
        base.update(overrides)
        return base

    def test_minimal_valid(self) -> None:
        """Minimale Payload — alle Defaults greifen."""
        payload = PrinterCreatePayload(**self._minimal())  # type: ignore[arg-type]
        assert payload.name == "Brother P-750W"
        assert payload.slug == "brother-p750w"
        assert payload.enabled is True
        assert payload.queue.timeout_s == 30
        assert payload.cut_defaults.half_cut is False

    def test_slug_uppercase_rejected(self) -> None:
        """Slug darf keine Großbuchstaben enthalten."""
        with pytest.raises(ValidationError):
            PrinterCreatePayload(**self._minimal(slug="Brother-P750W"))  # type: ignore[arg-type]

    def test_slug_underscore_rejected(self) -> None:
        with pytest.raises(ValidationError):
            PrinterCreatePayload(**self._minimal(slug="brother_p750w"))  # type: ignore[arg-type]

    def test_slug_too_short_rejected(self) -> None:
        """Slug braucht mindestens 3 Zeichen (Prefix + Trennzeichen + Suffix)."""
        with pytest.raises(ValidationError):
            PrinterCreatePayload(**self._minimal(slug="ab"))  # type: ignore[arg-type]

    def test_slug_valid_with_numbers(self) -> None:
        payload = PrinterCreatePayload(**self._minimal(slug="ql-820nwb"))  # type: ignore[arg-type]
        assert payload.slug == "ql-820nwb"

    def test_backend_ptouch_valid(self) -> None:
        payload = PrinterCreatePayload(**self._minimal(backend="ptouch"))  # type: ignore[arg-type]
        assert payload.backend == "ptouch"

    def test_backend_brother_ql_valid(self) -> None:
        payload = PrinterCreatePayload(**self._minimal(backend="brother_ql"))  # type: ignore[arg-type]
        assert payload.backend == "brother_ql"

    def test_backend_unknown_rejected(self) -> None:
        """Unbekanntes Backend muss ValidationError werfen."""
        with pytest.raises(ValidationError):
            PrinterCreatePayload(**self._minimal(backend="cups"))  # type: ignore[arg-type]

    def test_backend_empty_rejected(self) -> None:
        with pytest.raises(ValidationError):
            PrinterCreatePayload(**self._minimal(backend=""))  # type: ignore[arg-type]

    def test_name_empty_rejected(self) -> None:
        with pytest.raises(ValidationError):
            PrinterCreatePayload(**self._minimal(name=""))  # type: ignore[arg-type]

    def test_enabled_default_true(self) -> None:
        payload = PrinterCreatePayload(**self._minimal())  # type: ignore[arg-type]
        assert payload.enabled is True

    def test_enabled_false_explicit(self) -> None:
        payload = PrinterCreatePayload(**self._minimal(enabled=False))  # type: ignore[arg-type]
        assert payload.enabled is False

    def test_full_payload(self) -> None:
        """Komplett ausgefüllte Payload mit allen optionalen Feldern."""
        payload = PrinterCreatePayload(
            name="QL-820NWB Lager",
            slug="ql-820nwb-lager",
            model="QL-820NWB",
            backend="brother_ql",
            connection=PrinterConnection(
                host="192.0.2.20",
                port=9100,
                snmp=SNMPConfig(discover=True, community="private"),
            ),
            queue=PrinterQueueSettings(timeout_s=60),
            cut_defaults=PrinterCutDefaults(half_cut=False),
            enabled=False,
        )
        assert payload.enabled is False
        assert payload.queue.timeout_s == 60
        assert payload.connection.snmp.community == "private"


# ---------------------------------------------------------------------------
# PrinterUpdatePayload
# ---------------------------------------------------------------------------


class TestPrinterUpdatePayload:
    def test_empty_patch_valid(self) -> None:
        """Leere Update-Payload ist gültig (alle Felder optional)."""
        patch = PrinterUpdatePayload()
        assert patch.name is None
        assert patch.connection is None
        assert patch.queue is None
        assert patch.cut_defaults is None
        assert patch.enabled is None

    def test_partial_patch_name_only(self) -> None:
        patch = PrinterUpdatePayload(name="Neuer Name")
        assert patch.name == "Neuer Name"
        assert patch.enabled is None

    def test_partial_patch_enabled_only(self) -> None:
        patch = PrinterUpdatePayload(enabled=False)
        assert patch.enabled is False
        assert patch.name is None

    def test_partial_patch_connection(self) -> None:
        patch = PrinterUpdatePayload(connection=PrinterConnection(host="192.0.2.99", port=9100))
        assert patch.connection is not None
        assert patch.connection.host == "192.0.2.99"

    def test_partial_patch_queue(self) -> None:
        patch = PrinterUpdatePayload(queue=PrinterQueueSettings(timeout_s=120))
        assert patch.queue is not None
        assert patch.queue.timeout_s == 120

    def test_partial_patch_cut_defaults(self) -> None:
        patch = PrinterUpdatePayload(cut_defaults=PrinterCutDefaults(half_cut=False))
        assert patch.cut_defaults is not None
        assert patch.cut_defaults.half_cut is False
