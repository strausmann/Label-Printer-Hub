"""Phase 7b Cluster 1e — ReadinessResponse + CheckStatus schema tests."""

from app.schemas.readiness import CheckStatus, ReadinessResponse


def test_check_status_minimum_fields():
    c = CheckStatus(status="ok")
    assert c.status == "ok"
    assert c.detail is None
    assert c.metric is None


def test_check_status_accepts_all_statuses():
    for s in ("ok", "fail", "skipped", "stale"):
        assert CheckStatus(status=s).status == s


def test_readiness_response_aggregate():
    body = ReadinessResponse(
        status="ready",
        checks={"database": CheckStatus(status="ok", metric={"latency_ms": 0.8})},
        version="dev",
        revision="abc",
    )
    assert body.status == "ready"
    assert body.checks["database"].metric == {"latency_ms": 0.8}


def test_readiness_response_status_values():
    for s in ("ready", "degraded", "not-ready"):
        assert ReadinessResponse(status=s, checks={}, version="v", revision="r").status == s
