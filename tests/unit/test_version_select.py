"""Version-aware ordering/predecessor selection (modules.search.versions).

A later-ingested OLDER snapshot must never sort above a newer release, and the
"predecessor" of a version must be the previous RELEASE, not whatever was
ingested just before it (the SIO 1.34.0-vs-1.62 bug).
"""
import datetime as dt

from ontoexplorer.modules.search import versions as V


class _V:
    def __init__(self, vid, version_iri, status="ready", created=None):
        self.id = vid
        self.version_iri = version_iri
        self.status = status
        self.created_at = created or dt.datetime(2026, 1, 1)


# SIO's real shape: the 1.34.0 snapshot was INGESTED after 1.61.
def _sio():
    return [
        _V("c162", "http://x/sio/v1.62/o", created=dt.datetime(2026, 10, 13)),
        _V("a134", "http://x/sio/v1.34.0/o", created=dt.datetime(2026, 9, 21)),
        _V("b161", "http://x/sio/v1.61/o", created=dt.datetime(2026, 9, 14)),
    ]


def test_sort_is_version_aware_not_ingest_order():
    assert [v.id for v in V.sort_versions(_sio())] == ["c162", "b161", "a134"]


def test_choose_picks_highest_version_not_latest_ingest():
    assert V._choose(_sio(), None).id == "c162"


def test_predecessor_is_previous_release_not_previous_ingest():
    # predecessor of 1.62 is 1.61 — NOT the later-ingested 1.34.0 snapshot.
    assert V.version_predecessor(_sio(), "c162").id == "b161"


def test_predecessor_of_middle_version():
    assert V.version_predecessor(_sio(), "b161").id == "a134"


def test_predecessor_none_for_oldest():
    assert V.version_predecessor(_sio(), "a134") is None


def test_predecessor_skips_non_ready():
    vs = [
        _V("new", "http://x/v2.0/o"),
        _V("mid", "http://x/v1.5/o", status="failed"),
        _V("old", "http://x/v1.0/o"),
    ]
    # the v1.5 is failed -> predecessor of v2.0 is the ready v1.0
    assert V.version_predecessor(vs, "new").id == "old"


def test_choose_excludes_needs_review():
    # A version held by the quality gate (#364) must never win the default, even
    # when it is the highest version — the public ontology page / search scope
    # resolve the default via _choose.
    vs = [
        _V("held", "http://x/v2.0/o", status="needs_review"),
        _V("ok", "http://x/v1.0/o"),
    ]
    assert V._choose(vs, None).id == "ok"


def test_choose_none_when_only_needs_review():
    vs = [_V("held", "http://x/v1.0/o", status="needs_review")]
    assert V._choose(vs, None) is None


def test_pinned_needs_review_is_not_honored():
    # Even an explicit pin cannot surface a held version as the public default.
    vs = [
        _V("held", "http://x/v2.0/o", status="needs_review"),
        _V("ok", "http://x/v1.0/o"),
    ]
    assert V._choose(vs, "held").id == "ok"


def test_predecessor_skips_needs_review():
    vs = [
        _V("new", "http://x/v2.0/o"),
        _V("mid", "http://x/v1.5/o", status="needs_review"),
        _V("old", "http://x/v1.0/o"),
    ]
    # a held v1.5 is not a valid diff baseline -> predecessor of v2.0 is v1.0
    assert V.version_predecessor(vs, "new").id == "old"


def test_date_versioned_iris():
    vs = [
        _V("x", "http://x/2024-05-01/o"),
        _V("y", "http://x/2024-01-01/o"),
    ]
    assert [v.id for v in V.sort_versions(vs)] == ["x", "y"]
    assert V.version_predecessor(vs, "x").id == "y"
