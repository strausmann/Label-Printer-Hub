# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The id of a new printer row.

Until 1.7.1 a printer's id was a UUIDv5 over ``model|host|port|created_at`` with a namespace
that sits in the public repository. Every read key sees the id, the model and ``created_at``, so
the address could be recovered offline by hashing candidate hosts and ports (run-30 R30-3). A new
printer now gets a random UUIDv4 that says nothing about where it is.

Rows created earlier keep their id: nothing derives an id to find a printer (rows are looked up
by id, slug or name), so no migration is needed and the old ids simply stay.
"""

from __future__ import annotations

import uuid


def new_printer_id() -> uuid.UUID:
    """A fresh random id for a printer that is being created."""
    return uuid.uuid4()
