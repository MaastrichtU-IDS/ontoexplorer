"""Unit tests for usage trend bucketing helpers (pure; DB-free)."""
from datetime import date

from ontoexplorer.modules.usage.query import (
    _add_months,
    build_series,
    build_trend,
    period_label,
    period_starts,
)


def test_add_months_wraps_year():
    assert _add_months(date(2026, 7, 15), -8) == date(2025, 11, 1)
    assert _add_months(date(2026, 12, 1), 1) == date(2027, 1, 1)


def test_period_starts_month():
    starts = period_starts("month", 3, date(2026, 7, 25))
    assert starts == [date(2026, 5, 1), date(2026, 6, 1), date(2026, 7, 1)]


def test_period_starts_year():
    assert period_starts("year", 3, date(2026, 7, 25)) == [
        date(2024, 1, 1), date(2025, 1, 1), date(2026, 1, 1),
    ]


def test_period_starts_week_is_monday_aligned():
    # 2026-07-25 is a Saturday; its ISO week starts Monday 2026-07-20.
    starts = period_starts("week", 2, date(2026, 7, 25))
    assert starts == [date(2026, 7, 13), date(2026, 7, 20)]


def test_period_label():
    assert period_label("year", date(2026, 1, 1)) == "2026"
    assert period_label("month", date(2026, 7, 1)) == "2026-07"
    assert period_label("week", date(2026, 7, 20)) == "2026-07-20"


def test_build_trend_zero_fills_and_orders():
    today = date(2026, 7, 25)
    tmap = {date(2026, 7, 1): {"view_unique": 3, "view_total": 5,
                               "download_unique": 1, "download_total": 2}}
    trend = build_trend("month", 3, today, tmap)
    assert [t["period"] for t in trend] == ["2026-05", "2026-06", "2026-07"]
    assert trend[0] == {"period": "2026-05", "view_unique": 0, "view_total": 0,
                        "download_unique": 0, "download_total": 0}
    assert trend[2]["view_unique"] == 3 and trend[2]["download_total"] == 2


def test_build_series_zero_fills_per_ontology():
    today = date(2026, 7, 25)
    points = {date(2026, 6, 1): {"unique": 4, "total": 9}}
    series = build_series("month", 3, today, points)
    assert [p["period"] for p in series] == ["2026-05", "2026-06", "2026-07"]
    assert series[0] == {"period": "2026-05", "unique": 0, "total": 0}
    assert series[1] == {"period": "2026-06", "unique": 4, "total": 9}
    assert series[2] == {"period": "2026-07", "unique": 0, "total": 0}
