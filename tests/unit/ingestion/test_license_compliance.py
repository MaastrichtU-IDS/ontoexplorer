"""License canonicalization → SPDX + platform-compliance check (#364)."""
import pytest

from ontoexplorer.config import get_settings
from ontoexplorer.modules.ingestion.license import (
    canonicalize_license,
    is_compliant,
)


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
])
def test_canonicalize(raw, spdx):
    assert canonicalize_license(raw) == spdx


def test_unknown_license_is_none():
    assert canonicalize_license("All rights reserved") is None
    assert canonicalize_license("") is None
    assert canonicalize_license(None) is None


def test_compliance_default_allowlist(monkeypatch):
    # Default allowlist = open licenses, excludes NonCommercial/NoDerivatives.
    assert is_compliant("https://creativecommons.org/licenses/by/4.0/") is True
    assert is_compliant("CC0-1.0") is True
    assert is_compliant("MIT") is True
    # NonCommercial is NOT on the default allowlist.
    assert is_compliant("https://creativecommons.org/licenses/by-nc/4.0/") is False
    # Unrecognized → not compliant (goes to review, not auto-published).
    assert is_compliant("All rights reserved") is False
    assert is_compliant(None) is False


def test_empty_allowlist_disables_gate(monkeypatch):
    monkeypatch.setattr(get_settings(), "compliant_licenses", "", raising=False)
    assert is_compliant("anything at all") is True
    assert is_compliant(None) is True
