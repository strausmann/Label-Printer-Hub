# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""``tape_config``: the runtime config of a stored tape printer."""

from __future__ import annotations

from types import SimpleNamespace

from app.services.printer_runtime import tape_config


def test_tape_config_maps_a_stored_tape_row() -> None:
    row = SimpleNamespace(
        slug="workshop",
        name="Workshop",
        backend="ptouch",
        model="PT-P750W",
        connection={
            "host": "192.0.2.10",
            "port": 9101,
            "snmp": {"discover": True, "community": "private"},
        },
        queue_timeout_s=45,
        cut_defaults_half_cut=True,
    )
    cfg = tape_config(row)
    assert (cfg.slug, cfg.name, cfg.backend, cfg.model) == (
        "workshop",
        "Workshop",
        "ptouch",
        "PT-P750W",
    )
    assert (cfg.host, cfg.port) == ("192.0.2.10", 9101)
    assert (cfg.snmp.discover, cfg.snmp.community) == (True, "private")
    assert cfg.queue.timeout_s == 45
    assert cfg.cut_defaults.half_cut is True


def test_tape_config_gives_missing_connection_fields_defaults() -> None:
    row = SimpleNamespace(
        slug="workshop",
        name="Workshop",
        backend="ptouch",
        model="PT-P750W",
        connection=None,
    )
    cfg = tape_config(row)
    assert (cfg.host, cfg.port) == ("", 9100)
    assert (cfg.snmp.discover, cfg.snmp.community) == (False, "public")
    assert cfg.queue.timeout_s == 30
    assert cfg.cut_defaults.half_cut is False
