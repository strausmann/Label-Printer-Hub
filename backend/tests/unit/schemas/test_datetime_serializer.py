import datetime

from app.schemas._datetime import serialize_datetime_utc


def test_naive_datetime_gets_utc_tz_and_z_suffix():
    naive = datetime.datetime(2026, 5, 17, 12, 0, 0)
    assert serialize_datetime_utc(naive, None) == "2026-05-17T12:00:00Z"


def test_utc_aware_datetime_serialised_with_z_suffix():
    aware = datetime.datetime(2026, 5, 17, 12, 0, 0, tzinfo=datetime.UTC)
    assert serialize_datetime_utc(aware, None) == "2026-05-17T12:00:00Z"


def test_non_utc_aware_datetime_kept_with_offset():
    plus_two = datetime.datetime(
        2026, 5, 17, 14, 0, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=2))
    )
    assert serialize_datetime_utc(plus_two, None) == "2026-05-17T14:00:00+02:00"
