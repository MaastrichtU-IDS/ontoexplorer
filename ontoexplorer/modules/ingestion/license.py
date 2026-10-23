"""Canonicalize a declared ontology license to an SPDX id and check whether it is
on the platform's compliance allowlist (#364).

Ontologies declare a license a dozen ways — a URL (`http://creativecommons.org/
licenses/by/4.0/`), a label (`CC BY 4.0`), or an SPDX id directly. We map the known
open licenses to SPDX, then compare against `settings.compliant_licenses`. An
unrecognized/unmappable license canonicalizes to None → treated as non-compliant
(so it can't be auto-published; it goes to review).
"""
from __future__ import annotations

import re

from ontoexplorer.config import get_settings

# URL-fragment → SPDX. Checked in order; first match wins (so by-nc/by-nd are
# caught before the plain by-* patterns they'd otherwise substring-match).
_URL_TO_SPDX: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"creativecommons\.org/publicdomain/zero/1\.0"), "CC0-1.0"),
    (re.compile(r"creativecommons\.org/licenses/by-nc-nd/(\d)\.0"), "CC-BY-NC-ND"),
    (re.compile(r"creativecommons\.org/licenses/by-nc-sa/(\d)\.0"), "CC-BY-NC-SA"),
    (re.compile(r"creativecommons\.org/licenses/by-nc/(\d)\.0"), "CC-BY-NC"),
    (re.compile(r"creativecommons\.org/licenses/by-nd/(\d)\.0"), "CC-BY-ND"),
    (re.compile(r"creativecommons\.org/licenses/by-sa/4\.0"), "CC-BY-SA-4.0"),
    (re.compile(r"creativecommons\.org/licenses/by-sa/3\.0"), "CC-BY-SA-3.0"),
    (re.compile(r"creativecommons\.org/licenses/by/4\.0"), "CC-BY-4.0"),
    (re.compile(r"creativecommons\.org/licenses/by/3\.0"), "CC-BY-3.0"),
    (re.compile(r"apache\.org/licenses/LICENSE-2\.0"), "Apache-2.0"),
    (re.compile(r"opensource\.org/licenses/MIT"), "MIT"),
    (re.compile(r"opensource\.org/licenses/BSD-3-Clause"), "BSD-3-Clause"),
    (re.compile(r"gnu\.org/licenses/gpl-3\.0"), "GPL-3.0-only"),
)

# Free-text label (lowercased, punctuation-normalized) → SPDX.
_LABEL_TO_SPDX: dict[str, str] = {
    "cc0": "CC0-1.0", "cc0 1.0": "CC0-1.0", "public domain": "CC0-1.0",
    "cc by 4.0": "CC-BY-4.0", "cc-by 4.0": "CC-BY-4.0", "cc by": "CC-BY-4.0",
    "cc by 3.0": "CC-BY-3.0",
    "cc by-sa 4.0": "CC-BY-SA-4.0", "cc by sa 4.0": "CC-BY-SA-4.0",
    "cc by-sa 3.0": "CC-BY-SA-3.0",
    "mit": "MIT", "mit license": "MIT",
    "apache 2.0": "Apache-2.0", "apache-2.0": "Apache-2.0", "apache license 2.0": "Apache-2.0",
    "bsd-3-clause": "BSD-3-Clause", "bsd 3 clause": "BSD-3-Clause",
    "gpl 3.0": "GPL-3.0-only", "gpl-3.0": "GPL-3.0-only",
}

# SPDX ids we recognize (so a value already in SPDX form passes through).
_KNOWN_SPDX: frozenset[str] = frozenset(
    list(_LABEL_TO_SPDX.values())
    + [s for _, s in _URL_TO_SPDX]
)


def canonicalize_license(raw: str | None) -> str | None:
    """Map a declared license (URL, label, or SPDX id) to a canonical SPDX id, or
    None if unrecognized."""
    if not raw:
        return None
    s = raw.strip()
    if not s:
        return None
    # Already an SPDX id we know?
    if s in _KNOWN_SPDX:
        return s
    for pat, spdx in _URL_TO_SPDX:
        if pat.search(s):
            return spdx
    key = re.sub(r"\s+", " ", s.lower().replace("_", " ").replace("/", " ")).strip()
    return _LABEL_TO_SPDX.get(key)


def compliant_license_set() -> set[str]:
    return {x.strip() for x in get_settings().compliant_licenses.split(",") if x.strip()}


def effective_license(
    content_license: str | None, declared_license: str | None,
) -> tuple[str | None, str | None, bool]:
    """Resolve compliance from the content license plus a contributor's declared
    overlay (#364 Add-Ontology flow). Returns (content_spdx, declared_spdx,
    license_compliant).

    The overlay fills an ABSENCE only: a RECOGNIZED content license decides on its
    own, so a declared non-compliant license (e.g. CC-BY-NC, which the canonicalizer
    recognizes) still fails the gate and a contributor cannot launder it. Only when
    the content declares no recognized license does the contributor's
    `declared_license` apply. An empty allowlist disables the gate.
    """
    allow = compliant_license_set()
    content_spdx = canonicalize_license(content_license)
    declared_spdx = canonicalize_license(declared_license)
    if not allow:
        return content_spdx, declared_spdx, True
    if content_spdx is not None:
        return content_spdx, declared_spdx, content_spdx in allow
    return content_spdx, declared_spdx, bool(declared_spdx and declared_spdx in allow)


def is_compliant(raw: str | None) -> bool:
    """True if the declared license canonicalizes to an SPDX id on the platform
    allowlist. An empty allowlist disables the gate (everything compliant)."""
    allow = compliant_license_set()
    if not allow:
        return True
    return canonicalize_license(raw) in allow


def decide_publish_status(
    current_status: str, *,
    license_compliant: bool, triple_count: int | None, title: str | None,
    min_triples: int,
) -> tuple[str, list[str]]:
    """Pre-publish quality gate (#364). Decide the status at the index task's
    ingested->ready transition. Returns (new_status, reasons-it-was-held).

    - An already-`ready` version is NEVER demoted (re-index is a no-op here) — this
      protects the existing catalogue; the gate only judges first publication (from
      `ingested`/`needs_review`).
    - Otherwise: publish (`ready`) only if license-compliant, above the triple floor,
      and titled; else hold for review (`needs_review`).
    """
    if current_status == "ready":
        return "ready", []
    reasons = held_reasons(
        license_compliant=license_compliant, triple_count=triple_count,
        title=title, min_triples=min_triples,
    )
    return ("ready" if not reasons else "needs_review"), reasons


def held_reasons(
    *, license_compliant: bool, triple_count: int | None, title: str | None,
    min_triples: int,
) -> list[str]:
    """The quality-gate reasons a version is (or would be) held for review — empty
    means it passes. Shared by `decide_publish_status` and by the admin review
    surface to show WHY a held version is held (recomputed from stored signals, so
    it also reflects fixes made since the original ingest)."""
    reasons: list[str] = []
    if not license_compliant:
        reasons.append("license missing or not on the platform compliance allowlist")
    if (triple_count or 0) < min_triples:
        reasons.append(f"fewer than {min_triples} triple(s)")
    if not (title or "").strip():
        reasons.append("no title")
    return reasons
