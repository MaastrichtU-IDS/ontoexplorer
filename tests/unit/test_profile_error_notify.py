"""_maybe_notify_owner_profile_error: emails the owner once, only for owner-actionable
profile-failure categories, deduped via profile_error_notified_at — so re-ingests and
the re-profile backfill never re-email."""
import pytest

from ontoexplorer.modules.jobs import tasks

pytestmark = pytest.mark.anyio


class _Res:
    def __init__(self, scalar="__none__", first=None):
        self._scalar, self._first = scalar, first

    def scalar_one_or_none(self):
        return None if self._scalar == "__none__" else self._scalar

    def first(self):
        return self._first


class _Owner:
    title, shortname, email, display_name = "My Ont", "myont", "owner@example.org", "Pat"


class _DB:
    """Returns: 1) the notified-at check, 2) the owner row, 3) the update. Records commit."""
    def __init__(self, already_notified=None, owner=_Owner()):
        self._queue = [_Res(scalar=already_notified), _Res(first=owner), _Res()]
        self.commits = 0
        self.executed = 0

    async def execute(self, *a, **k):
        self.executed += 1
        return self._queue.pop(0) if self._queue else _Res()

    async def commit(self):
        self.commits += 1


def _payload(category, detail="X is typed voaf:Vocabulary ..."):
    return {"profiles_unavailable": True, "profiles_error_category": category,
            "profiles_error_detail": detail}


async def test_emails_once_for_actionable_category(monkeypatch):
    sent = []
    async def _fake(**kw):
        sent.append(kw)
    monkeypatch.setattr("ontoexplorer.modules.notifications.email.notify_owner_profile_uncomputable", _fake)

    db = _DB(already_notified=None)
    await tasks._maybe_notify_owner_profile_error(db, "v1", "o1", _payload("equivalent_class_undeclared"))
    assert len(sent) == 1
    assert sent[0]["owner_email"] == "owner@example.org"
    assert sent[0]["ontology_label"] == "My Ont"
    assert db.commits == 1                      # profile_error_notified_at stamped


async def test_no_email_for_nonactionable_category(monkeypatch):
    sent = []
    monkeypatch.setattr("ontoexplorer.modules.notifications.email.notify_owner_profile_uncomputable",
                        lambda **kw: sent.append(kw))
    db = _DB(already_notified=None)
    # invalid_annotation (voaf typing) is NOT owner-actionable -> never emailed
    await tasks._maybe_notify_owner_profile_error(db, "v1", "o1", _payload("invalid_annotation"))
    assert sent == []
    assert db.executed == 0 and db.commits == 0  # returns before any DB work


async def test_dedup_when_already_notified(monkeypatch):
    import datetime as _dt
    sent = []
    monkeypatch.setattr("ontoexplorer.modules.notifications.email.notify_owner_profile_uncomputable",
                        lambda **kw: sent.append(kw))
    db = _DB(already_notified=_dt.datetime(2026, 11, 14, tzinfo=_dt.timezone.utc))
    await tasks._maybe_notify_owner_profile_error(db, "v1", "o1", _payload("property_kind"))
    assert sent == []            # already notified -> no second email
    assert db.commits == 0


async def test_actionable_set_excludes_strict_parser_cases():
    assert "invalid_annotation" not in tasks._ACTIONABLE_PROFILE_ERRORS
    assert "other" not in tasks._ACTIONABLE_PROFILE_ERRORS
    assert {"equivalent_class_undeclared", "property_kind",
            "annotation_property_equivalent", "rdf_syntax"} <= tasks._ACTIONABLE_PROFILE_ERRORS
