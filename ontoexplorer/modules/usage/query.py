"""Read-side aggregation over usage_daily.

Daily rows are grouped into week/month/year buckets on read via date_trunc, so
no second table is needed. Callers pass a validated granularity from
GRANULARITIES; nothing here interpolates user input into SQL (date_trunc's field
is a bind param, ontology ids go through ANY(:oids)).
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

GRANULARITIES = frozenset({"week", "month", "year"})
MAX_PERIODS = 60


def _add_months(d: date, months: int) -> date:
    m = d.month - 1 + months
    return date(d.year + m // 12, m % 12 + 1, 1)


def period_starts(granularity: str, periods: int, today: date) -> list[date]:
    """Dense, ascending list of the last `periods` bucket-start dates (UTC)."""
    if granularity == "year":
        return [date(today.year - k, 1, 1) for k in range(periods - 1, -1, -1)]
    if granularity == "week":
        monday = today - timedelta(days=today.weekday())  # matches date_trunc('week')
        return [monday - timedelta(weeks=k) for k in range(periods - 1, -1, -1)]
    cur = date(today.year, today.month, 1)
    return [_add_months(cur, -k) for k in range(periods - 1, -1, -1)]


def period_label(granularity: str, d: date) -> str:
    if granularity == "year":
        return f"{d.year:04d}"
    if granularity == "month":
        return f"{d.year:04d}-{d.month:02d}"
    return d.isoformat()  # week → Monday's ISO date


async def usage_totals(db: AsyncSession, ontology_ids: list[str] | None = None) -> dict:
    """All-time totals per kind: {views:{unique,total}, downloads:{unique,total}}."""
    where, params = "", {}
    if ontology_ids is not None:
        where = "WHERE ontology_id = ANY(:oids)"
        params["oids"] = ontology_ids
    sql = text(
        f"SELECT kind, COALESCE(SUM(unique_count),0), COALESCE(SUM(total_count),0) "
        f"FROM usage_daily {where} GROUP BY kind"
    )
    totals = {"views": {"unique": 0, "total": 0}, "downloads": {"unique": 0, "total": 0}}
    keymap = {"view": "views", "download": "downloads"}
    for kind, uq, tot in (await db.execute(sql, params)).all():
        k = keymap.get(kind)
        if k:
            totals[k] = {"unique": int(uq), "total": int(tot)}
    return totals


async def usage_trend(
    db: AsyncSession, granularity: str, since: date, ontology_ids: list[str] | None = None,
) -> dict[date, dict]:
    """Bucketed sums keyed by bucket-start date (>= since). Sparse — zero-fill on read."""
    where = "day >= :since"
    params: dict = {"g": granularity, "since": since}
    if ontology_ids is not None:
        where += " AND ontology_id = ANY(:oids)"
        params["oids"] = ontology_ids
    sql = text(f"""
        SELECT date_trunc(:g, day::timestamp) AS period,
               COALESCE(SUM(unique_count) FILTER (WHERE kind='view'), 0)     AS vu,
               COALESCE(SUM(total_count)  FILTER (WHERE kind='view'), 0)     AS vt,
               COALESCE(SUM(unique_count) FILTER (WHERE kind='download'), 0) AS du,
               COALESCE(SUM(total_count)  FILTER (WHERE kind='download'), 0) AS dt
        FROM usage_daily
        WHERE {where}
        GROUP BY period
    """)
    out: dict[date, dict] = {}
    for period, vu, vt, du, dt in (await db.execute(sql, params)).all():
        out[period.date()] = {
            "view_unique": int(vu), "view_total": int(vt),
            "download_unique": int(du), "download_total": int(dt),
        }
    return out


async def usage_per_ontology(db: AsyncSession, ontology_ids: list[str]) -> list[dict]:
    """All-time view/download counts per ontology (LEFT JOIN so zero-usage
    ontologies still appear), ordered by most-active first."""
    if not ontology_ids:
        return []
    sql = text("""
        SELECT o.id, o.shortname, o.title,
               COALESCE(SUM(u.unique_count) FILTER (WHERE u.kind='view'), 0)     AS vu,
               COALESCE(SUM(u.total_count)  FILTER (WHERE u.kind='view'), 0)     AS vt,
               COALESCE(SUM(u.unique_count) FILTER (WHERE u.kind='download'), 0) AS du,
               COALESCE(SUM(u.total_count)  FILTER (WHERE u.kind='download'), 0) AS dt
        FROM ontologies o
        LEFT JOIN usage_daily u ON u.ontology_id = o.id
        WHERE o.id = ANY(:ids)
        GROUP BY o.id, o.shortname, o.title
        ORDER BY (COALESCE(SUM(u.total_count), 0)) DESC, o.shortname
    """)
    rows = (await db.execute(sql, {"ids": ontology_ids})).all()
    return [
        {
            "ontology_id": oid, "shortname": shortname, "title": title,
            "view_unique": int(vu), "view_total": int(vt),
            "download_unique": int(du), "download_total": int(dt),
        }
        for oid, shortname, title, vu, vt, du, dt in rows
    ]


async def usage_timeseries(
    db: AsyncSession, ontology_ids: list[str], kind: str, granularity: str, since: date,
) -> dict[str, dict[date, dict]]:
    """Per-ontology bucketed counts for one kind: {ontology_id: {bucket_date: {unique,total}}}.

    Sparse — the caller zero-fills against a dense period axis.
    """
    if not ontology_ids:
        return {}
    sql = text("""
        SELECT ontology_id, date_trunc(:g, day::timestamp) AS period,
               COALESCE(SUM(unique_count), 0) AS uq,
               COALESCE(SUM(total_count), 0)  AS tot
        FROM usage_daily
        WHERE kind = :kind AND day >= :since AND ontology_id = ANY(:ids)
        GROUP BY ontology_id, period
    """)
    params = {"g": granularity, "kind": kind, "since": since, "ids": ontology_ids}
    out: dict[str, dict[date, dict]] = {}
    for oid, period, uq, tot in (await db.execute(sql, params)).all():
        out.setdefault(oid, {})[period.date()] = {"unique": int(uq), "total": int(tot)}
    return out


def build_series(
    granularity: str, periods: int, today: date, points: dict[date, dict],
) -> list[dict]:
    """Dense, labelled, ascending per-ontology series (zero-filled)."""
    empty = {"unique": 0, "total": 0}
    return [
        {"period": period_label(granularity, s), **points.get(s, empty)}
        for s in period_starts(granularity, periods, today)
    ]


def build_trend(granularity: str, periods: int, today: date, tmap: dict[date, dict]) -> list[dict]:
    """Zero-filled, labelled, ascending trend series over the last `periods` buckets."""
    empty = {"view_unique": 0, "view_total": 0, "download_unique": 0, "download_total": 0}
    return [
        {"period": period_label(granularity, s), **tmap.get(s, empty)}
        for s in period_starts(granularity, periods, today)
    ]
