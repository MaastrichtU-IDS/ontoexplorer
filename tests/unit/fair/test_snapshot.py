"""Fairness-over-time: daily snapshot capture is idempotent, history reads back.

Aggregate correctness is covered in test_fleet.py; these pin the snapshot
plumbing (one upserted row per UTC day + the history series) against an empty
fleet, so no store/version fixtures are needed.
"""
from ontoexplorer.modules.fair.snapshot import capture_fair_snapshot, fair_history


async def test_capture_upserts_one_row_per_day(db_session):
    r1 = await capture_fair_snapshot(db_session)
    assert r1["day"] and r1["n"] == 0            # empty fleet → n=0, no error
    r2 = await capture_fair_snapshot(db_session)  # same UTC day
    assert r2["day"] == r1["day"]

    hist = await fair_history(db_session, days=30)
    assert len(hist) == 1                         # idempotent: one row, not two
    assert hist[0]["day"] == r1["day"]
    assert "overall_mean" in hist[0] and "principle_means" in hist[0]


async def test_history_empty_when_no_snapshots(db_session):
    from sqlalchemy import delete

    from ontoexplorer.models.db import FairSnapshot
    await db_session.execute(delete(FairSnapshot))
    await db_session.commit()
    assert await fair_history(db_session, days=30) == []
