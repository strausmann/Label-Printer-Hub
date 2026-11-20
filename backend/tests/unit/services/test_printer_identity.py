# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The id of a new printer carries nothing about the printer (run-30 R30-3)."""

from __future__ import annotations

import uuid

from app.services.printer_identity import new_printer_id

# The namespace of the ids that 1.7.0 and earlier derived. Copied here on purpose: the test
# recomputes the old derivation to show that a new id is not one of its results.
_OLD_NAMESPACE = uuid.UUID("6f1b3c7e-9d6a-4f48-9a8c-d4e0e1c5a3b2")


def test_new_ids_are_random_version_4_uuids() -> None:
    ids = {new_printer_id() for _ in range(200)}
    assert len(ids) == 200
    assert all(i.version == 4 for i in ids)


def test_a_new_id_is_not_the_old_derivation_of_any_attribute_set() -> None:
    salt = "pt-p750w|192.0.2.50|9100|2026-11-20T10:00:00+00:00"
    assert new_printer_id() != uuid.uuid5(_OLD_NAMESPACE, salt)
