"""Unit tests for ApiKey model and Job model extensions (Phase 7c)."""

from __future__ import annotations

from sqlalchemy import Boolean, DateTime, Integer, String


def test_api_key_model_importable():
    from app.models.api_key import ApiKey
    assert ApiKey is not None


def test_api_key_table_name():
    from app.models.api_key import ApiKey
    assert ApiKey.__tablename__ == "api_keys"


def test_api_key_has_uuid_primary_key():
    from app.models.api_key import ApiKey
    col = ApiKey.__table__.columns["id"]
    assert col.primary_key is True


def test_api_key_name_is_string_and_indexed():
    from app.models.api_key import ApiKey
    col = ApiKey.__table__.columns["name"]
    assert isinstance(col.type, String)
    index_cols = {c.name for idx in ApiKey.__table__.indexes for c in idx.columns}
    assert "name" in index_cols


def test_api_key_key_hash_is_string():
    from app.models.api_key import ApiKey
    col = ApiKey.__table__.columns["key_hash"]
    assert isinstance(col.type, String)
    assert col.nullable is False


def test_api_key_key_prefix_is_string_and_indexed():
    from app.models.api_key import ApiKey
    col = ApiKey.__table__.columns["key_prefix"]
    assert isinstance(col.type, String)
    index_cols = {c.name for idx in ApiKey.__table__.indexes for c in idx.columns}
    assert "key_prefix" in index_cols


def test_api_key_scopes_is_json():
    from app.models.api_key import ApiKey
    col = ApiKey.__table__.columns["scopes"]
    assert "json" in type(col.type).__name__.lower()
    assert col.nullable is False


def test_api_key_allowed_printer_ids_is_json():
    from app.models.api_key import ApiKey
    col = ApiKey.__table__.columns["allowed_printer_ids"]
    assert "json" in type(col.type).__name__.lower()
    assert col.nullable is False


def test_api_key_rate_limit_is_integer():
    from app.models.api_key import ApiKey
    col = ApiKey.__table__.columns["rate_limit_per_minute"]
    assert isinstance(col.type, Integer)


def test_api_key_enabled_is_boolean():
    from app.models.api_key import ApiKey
    col = ApiKey.__table__.columns["enabled"]
    assert isinstance(col.type, Boolean)


def test_api_key_created_at_timezone_aware():
    from app.models.api_key import ApiKey
    col = ApiKey.__table__.columns["created_at"]
    assert isinstance(col.type, DateTime)
    assert col.type.timezone is True


def test_api_key_last_used_at_nullable_datetime():
    from app.models.api_key import ApiKey
    col = ApiKey.__table__.columns["last_used_at"]
    assert isinstance(col.type, DateTime)
    assert col.nullable is True


def test_api_key_last_used_ip_nullable_string():
    from app.models.api_key import ApiKey
    col = ApiKey.__table__.columns["last_used_ip"]
    assert isinstance(col.type, String)
    assert col.nullable is True


def test_api_key_expires_at_nullable_datetime():
    from app.models.api_key import ApiKey
    col = ApiKey.__table__.columns["expires_at"]
    assert isinstance(col.type, DateTime)
    assert col.nullable is True


def test_api_key_notes_nullable_string():
    from app.models.api_key import ApiKey
    col = ApiKey.__table__.columns["notes"]
    assert isinstance(col.type, String)
    assert col.nullable is True


def test_api_key_default_values():
    from app.models.api_key import ApiKey
    key = ApiKey(
        name="test-key",
        key_hash="\$2b\$12\$fakehash",
        key_prefix="lh_ab12cd34",
        scopes=["read"],
    )
    assert key.enabled is True
    assert key.rate_limit_per_minute == 60
    assert key.allowed_printer_ids == []
    assert key.id is not None


def test_job_has_api_key_id_column():
    from app.models.job import Job
    col = Job.__table__.columns["api_key_id"]
    assert col.nullable is True


def test_job_has_source_ip_column():
    from app.models.job import Job
    col = Job.__table__.columns["source_ip"]
    assert isinstance(col.type, String)
    assert col.nullable is True


def test_job_api_key_id_defaults_none():
    from app.models.job import Job
    from uuid import uuid4
    job = Job(printer_id=uuid4(), template_key="test-template")
    assert job.api_key_id is None
    assert job.source_ip is None
