"""License canonicalization → SPDX + platform-compliance check (#364)."""
import pytest

from ontoexplorer.config import get_settings
from ontoexplorer.modules.ingestion.license import (
    canonicalize_license,
    decide_publish_status,
    effective_license,
    is_compliant,
    is_newly_held,
)


class TestIsNewlyHeld:
    """The owner "action needed" email fires only on the first hold — this predicate
    is what keeps a re-index of an already-held version from re-nagging (#364 2a)."""

    def test_first_hold_from_ingested(self):
        assert is_newly_held("ingested", "needs_review") is True

    def test_reindex_of_already_held_does_not_refire(self):
        assert is_newly_held("needs_review", "needs_review") is False

    def test_passing_is_not_a_hold(self):
        assert is_newly_held("ingested", "ready") is False

    def test_ready_version_never_newly_held(self):
        assert is_newly_held("ready", "ready") is False


class TestEffectiveLicenseOverlay:
    """The contributor overlay fills an ABSENCE only (#364 anti-laundering)."""

    def test_no_content_license_overlay_applies(self):
        _, _, ok = effective_license(None, "CC-BY-4.0")
        assert ok is True

    def test_no_content_no_declared_not_compliant(self):
        _, _, ok = effective_license(None, None)
        assert ok is False

    def test_recognized_compliant_content_passes(self):
        _, _, ok = effective_license("https://creativecommons.org/licenses/by/4.0/", None)
        assert ok is True

    def test_recognized_noncompliant_content_cannot_be_laundered(self):
        _, _, ok = effective_license(
            "http://creativecommons.org/licenses/by-nc/4.0/", "CC-BY-4.0")
        assert ok is False

    def test_present_but_unrecognized_content_cannot_be_laundered(self):
        # Present (not an absence) yet unmappable → holds; the overlay must not fill.
        _, _, ok = effective_license("All rights reserved (proprietary)", "CC-BY-4.0")
        assert ok is False

    def test_whitespace_only_content_is_absence(self):
        _, _, ok = effective_license("   ", "MIT")
        assert ok is True


@pytest.mark.parametrize("raw,spdx", [
    ("http://creativecommons.org/publicdomain/zero/1.0/", "CC0-1.0"),
    ("https://creativecommons.org/licenses/by/4.0/", "CC-BY-4.0"),
    ("http://creativecommons.org/licenses/by/3.0/", "CC-BY-3.0"),
    ("https://creativecommons.org/licenses/by-sa/4.0/", "CC-BY-SA-4.0"),
    ("http://www.apache.org/licenses/LICENSE-2.0", "Apache-2.0"),
    ("CC BY 4.0", "CC-BY-4.0"),
    ("cc0", "CC0-1.0"),
    ("MIT", "MIT"),
    ("Apache-2.0", "Apache-2.0"),          # already SPDX → passthrough
    ("https://creativecommons.org/licenses/by-nc/4.0/", "CC-BY-NC"),  # non-commercial detected
    # Older permissive CC versions must map too (the by/ and by-sa/ patterns were
    # pinned to 3.0/4.0, so 1.0–2.5 fell through to None and read as "no license").
    ("http://creativecommons.org/licenses/by/2.0/", "CC-BY-2.0"),
    ("https://creativecommons.org/licenses/by/2.5/", "CC-BY-2.5"),
    ("http://creativecommons.org/licenses/by/1.0/", "CC-BY-1.0"),
    ("http://creativecommons.org/licenses/by-sa/2.0/", "CC-BY-SA-2.0"),
    ("https://creativecommons.org/licenses/by-sa/2.5/", "CC-BY-SA-2.5"),
    ("http://creativecommons.org/licenses/by-sa/1.0/", "CC-BY-SA-1.0"),
    # Restrictive older versions still correctly recognized (and non-compliant).
    ("http://creativecommons.org/licenses/by-nc-sa/2.0/", "CC-BY-NC-SA"),
])
def test_canonicalize(raw, spdx):
    assert canonicalize_license(raw) == spdx


def test_plain_by_pattern_does_not_swallow_by_sa():
    # Order + specificity guard: a by-sa/2.0 URL must not be matched by the plain
    # by/2.0 pattern (it would mislabel a ShareAlike license as plain CC-BY).
    assert canonicalize_license(
        "http://creativecommons.org/licenses/by-sa/2.0/") == "CC-BY-SA-2.0"


def test_unknown_license_is_none():
    assert canonicalize_license("All rights reserved") is None
    assert canonicalize_license("") is None
    assert canonicalize_license(None) is None


def test_compliance_default_allowlist(monkeypatch):
    # Default allowlist = open licenses, excludes NonCommercial/NoDerivatives.
    assert is_compliant("https://creativecommons.org/licenses/by/4.0/") is True
    assert is_compliant("CC0-1.0") is True
    assert is_compliant("MIT") is True
    # Older permissive CC-BY / CC-BY-SA (2.x) are now on the default allowlist, so a
    # version declaring CC-BY-2.0 (e.g. linked-earth) publishes instead of being held.
    assert is_compliant("http://creativecommons.org/licenses/by/2.0/") is True
    assert is_compliant("https://creativecommons.org/licenses/by-sa/2.5/") is True
    # NonCommercial is NOT on the default allowlist.
    assert is_compliant("https://creativecommons.org/licenses/by-nc/4.0/") is False
    # ShareAlike-NonCommercial 2.0 also excluded (restricts reuse).
    assert is_compliant("http://creativecommons.org/licenses/by-nc-sa/2.0/") is False
    # Unrecognized → not compliant (goes to review, not auto-published).
    assert is_compliant("All rights reserved") is False
    assert is_compliant(None) is False


def test_empty_allowlist_disables_gate(monkeypatch):
    monkeypatch.setattr(get_settings(), "compliant_licenses", "", raising=False)
    assert is_compliant("anything at all") is True
    assert is_compliant(None) is True


# ── decide_publish_status (the pre-publish quality gate) ──────────────────────────

def _ok(**over):
    kw = dict(license_compliant=True, triple_count=100, title="GO", min_triples=1)
    kw.update(over)
    return kw


def test_gate_never_demotes_a_ready_version():
    # Re-index of an already-public version: everything "bad" but stays ready.
    status, reasons = decide_publish_status(
        "ready", license_compliant=False, triple_count=0, title=None, min_triples=1)
    assert status == "ready"
    assert reasons == []


def test_gate_publishes_a_good_first_ingest():
    status, reasons = decide_publish_status("ingested", **_ok())
    assert status == "ready"
    assert reasons == []


def test_gate_holds_non_compliant_license():
    status, reasons = decide_publish_status("ingested", **_ok(license_compliant=False))
    assert status == "needs_review"
    assert any("license" in r for r in reasons)


def test_gate_holds_empty_and_untitled():
    status, reasons = decide_publish_status(
        "ingested", **_ok(triple_count=0, title="  "))
    assert status == "needs_review"
    assert any("triple" in r for r in reasons)
    assert any("title" in r for r in reasons)


def test_gate_promotes_fixed_needs_review_on_reindex():
    # Held item, re-indexed after the license is fixed → publishes.
    status, reasons = decide_publish_status("needs_review", **_ok())
    assert status == "ready"
    assert reasons == []
