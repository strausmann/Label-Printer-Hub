"""Tests fuer audit_redaction.py — SNMP-Community Redaction Helper (Issue #124)."""

from __future__ import annotations

from app.services.audit_redaction import REDACTED, redact_secrets


def test_snmp_community_is_redacted_other_fields_unchanged() -> None:
    """SNMP-Community wird redacted; alle anderen Felder bleiben unverändert."""
    payload = {
        "slug": "brother-p750w",
        "connection": {
            "snmp": {
                "community": "public",
                "version": "2c",
            },
            "host": "192.0.2.10",
        },
    }
    result = redact_secrets(payload)

    assert result["connection"]["snmp"]["community"] == REDACTED
    assert result["connection"]["snmp"]["version"] == "2c"
    assert result["connection"]["host"] == "192.0.2.10"
    assert result["slug"] == "brother-p750w"


def test_input_is_not_mutated() -> None:
    """redact_secrets darf das Input-Dict NICHT verändern (deep copy)."""
    payload: dict[str, object] = {
        "connection": {
            "snmp": {
                "community": "secret",
            },
        },
    }
    original_community = "secret"
    redact_secrets(payload)

    # Original muss unberührt sein
    snmp = payload["connection"]  # type: ignore[index]
    assert snmp["snmp"]["community"] == original_community  # type: ignore[index]


def test_none_community_stays_none() -> None:
    """Community=None bleibt None — fehlende Werte werden nicht verschleiert."""
    payload = {
        "connection": {
            "snmp": {
                "community": None,
            },
        },
    }
    result = redact_secrets(payload)
    assert result["connection"]["snmp"]["community"] is None


def test_payload_without_snmp_block_unchanged() -> None:
    """Pre-Backfill payload ohne snmp-Block wird unverändert zurückgegeben."""
    payload = {
        "slug": "zebra-zpl",
        "connection": {
            "host": "192.0.2.5",
            "port": 9100,
        },
    }
    result = redact_secrets(payload)

    assert result == payload


def test_payload_without_connection_block_unchanged() -> None:
    """Payload ohne connection-Block wird unverändert zurückgegeben."""
    payload = {
        "slug": "virtual-printer",
        "backend": "dummy",
    }
    result = redact_secrets(payload)

    assert result == payload
