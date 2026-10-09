from datetime import datetime, timezone

from ontoexplorer.modules.resolve.conneg import parse_retry_after


def _now():
    return datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def test_parse_retry_after_date_and_seconds():
    # delta-seconds
    assert parse_retry_after("120", now=_now()) == datetime(2026, 1, 1, 12, 2, 0, tzinfo=timezone.utc)
    # HTTP-date
    got = parse_retry_after("Wed, 01 Jan 2026 12:05:00 GMT", now=_now())
    assert got == datetime(2026, 1, 1, 12, 5, 0, tzinfo=timezone.utc)
    # junk / missing → None (never raises)
    assert parse_retry_after("soon", now=_now()) is None
    assert parse_retry_after(None, now=_now()) is None
    assert parse_retry_after("  ", now=_now()) is None
