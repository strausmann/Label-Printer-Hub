"""``_limiter_key`` decides which sign-in rate-limit bucket a client address lands in (263-81).

One /64 is one subscriber, so a client rotating through its IPv6 addresses must not mint a
bucket per address. Documentation addresses only (RFC 5737, RFC 3849).
"""

from __future__ import annotations

import pytest
from app.api.routes.auth_session import _limiter_key


def test_ipv4_is_kept_as_is() -> None:
    assert _limiter_key("192.0.2.7") == "192.0.2.7"
    assert _limiter_key(" 192.0.2.7 ") == "192.0.2.7"


def test_ipv6_same_64_shares_bucket() -> None:
    first = _limiter_key("2001:db8:1:2::1")
    assert first == "2001:db8:1:2::/64"
    assert _limiter_key("2001:db8:1:2:aaaa:bbbb:cccc:dddd") == first
    assert _limiter_key("2001:DB8:1:2:0:0:0:9") == first
    assert _limiter_key("2001:db8:1:3::1") != first, "another /64 is another bucket"


def test_mapped_ipv4_equals_ipv4() -> None:
    assert _limiter_key("::ffff:192.0.2.7") == _limiter_key("192.0.2.7") == "192.0.2.7"
    assert _limiter_key("::ffff:c000:207") == "192.0.2.7"


def test_scope_id_dropped() -> None:
    assert _limiter_key("2001:db8:1:2::1%eth0") == _limiter_key("2001:db8:1:2::1")
    assert _limiter_key("2001:db8:1:2::1%2") == "2001:db8:1:2::/64"


@pytest.mark.parametrize("bad", ["evil-1", "999.1.1.1", "", " ", "a" * 500, None, "%eth0", "::1%"])
def test_garbage_is_unknown(bad: str | None) -> None:
    assert _limiter_key(bad) == "unknown"
