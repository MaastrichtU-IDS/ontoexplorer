"""Unit tests for _owner_public_fields — the public "Added by" identity shown on
the (unauthenticated) ontology Info page. Must expose display name + ORCID, never
email.
"""
from types import SimpleNamespace

from ontoexplorer.api.ontologies import _owner_public_fields


def _acct(provider, pid):
    return SimpleNamespace(provider=provider, provider_user_id=pid)


def test_none_owner():
    assert _owner_public_fields(None) == {"owner_display_name": None, "owner_orcid": None}


def test_orcid_owner():
    owner = SimpleNamespace(
        display_name="Ada Lovelace",
        email="ada@example.org",
        oauth_accounts=[_acct("github", "42"), _acct("orcid", "0000-0002-1825-0097")],
    )
    out = _owner_public_fields(owner)
    assert out == {"owner_display_name": "Ada Lovelace", "owner_orcid": "0000-0002-1825-0097"}
    # Never leak email.
    assert "owner_email" not in out
    assert "ada@example.org" not in out.values()


def test_non_orcid_owner_has_no_orcid():
    owner = SimpleNamespace(
        display_name="Grace", email="g@example.org", oauth_accounts=[_acct("github", "7")],
    )
    assert _owner_public_fields(owner) == {"owner_display_name": "Grace", "owner_orcid": None}


def test_bogus_orcid_none_string_ignored():
    # Guards against the historical (orcid, "None") catch-all rows.
    owner = SimpleNamespace(
        display_name="X", email="x@e.org", oauth_accounts=[_acct("orcid", "None")],
    )
    assert _owner_public_fields(owner)["owner_orcid"] is None
