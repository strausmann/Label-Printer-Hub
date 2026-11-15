# SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
# SPDX-License-Identifier: AGPL-3.0-or-later

"""aiosqlite's DEBUG logger prints every bound SQL parameter (263-50).

Run with a root logger at DEBUG, bound values (a device serial, a key hash) would reach the log
buffer and the console. The app pins that one logger to INFO at startup.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest
from app.main import create_app


@pytest.fixture
def restore_levels() -> Iterator[None]:
    names = ("aiosqlite", "")
    saved = {n: logging.getLogger(n).level for n in names}
    yield
    for n, level in saved.items():
        logging.getLogger(n).setLevel(level)


def test_aiosqlite_logger_pinned_to_info(restore_levels: None) -> None:
    logging.getLogger("aiosqlite").setLevel(logging.NOTSET)
    logging.getLogger().setLevel(logging.DEBUG)  # an operator debugging the app

    create_app()

    assert logging.getLogger("aiosqlite").level == logging.INFO
    assert not logging.getLogger("aiosqlite").isEnabledFor(logging.DEBUG)
    assert logging.getLogger("app").isEnabledFor(logging.DEBUG), "only aiosqlite is pinned"
