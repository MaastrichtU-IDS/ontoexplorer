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
# caught before the plain by-* patterns they'd otherwise substring-match). A value
# containing "{v}" is a template: the matched group (a version like "4.0", or a
# verbatim SPDX token for the spdx.org/dalicc catalogues) is substituted in.
# Canonicalization is version- and permission-COMPLETE: a NonCommercial/NoDerivatives
# or ShareAlike license still maps to its real SPDX id. Whether that id is on the
# platform's host/redistribute allowlist is a SEPARATE policy decision (is_compliant).
_URL_TO_SPDX: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"creativecommons\.org/publicdomain/zero/1\.0"), "CC0-1.0"),
    (re.compile(r"creativecommons\.org/public-?domain/(?:zero|cc0)"), "CC0-1.0"),
    # `licen[sc]es?` accepts American/British and singular/plural: license(s), licence(s).
    # Restrictive variants first, carrying the version straight from the URL ({v}).
    (re.compile(r"creativecommons\.org/licen[sc]es?/by-nc-nd/(\d\.\d)"), "CC-BY-NC-ND-{v}"),
    (re.compile(r"creativecommons\.org/licen[sc]es?/by-nc-sa/(\d\.\d)"), "CC-BY-NC-SA-{v}"),
    (re.compile(r"creativecommons\.org/licen[sc]es?/by-nc/(\d\.\d)"), "CC-BY-NC-{v}"),
    (re.compile(r"creativecommons\.org/licen[sc]es?/by-nd/(\d\.\d)"), "CC-BY-ND-{v}"),
    (re.compile(r"creativecommons\.org/licen[sc]es?/by-sa/(\d\.\d)"), "CC-BY-SA-{v}"),
    (re.compile(r"creativecommons\.org/licen[sc]es?/by/(\d\.\d)"), "CC-BY-{v}"),
    (re.compile(r"apache\.org/licenses/LICENSE-2\.0"), "Apache-2.0"),
    (re.compile(r"opensource\.org/licenses/MIT"), "MIT"),
    (re.compile(r"opensource\.org/licenses/BSD-3-Clause"), "BSD-3-Clause"),
    (re.compile(r"gnu\.org/licenses/gpl-3\.0"), "GPL-3.0-only"),
    # Standards-body permissive licenses (permit reuse + redistribution with notices).
    # W3C Software Notice and License (2002) — SPDX "W3C" — declared as the current
    # /copyright/software-license-2002 URL or the classic 2002 legal URL (e.g. fresnel).
    (re.compile(r"w3\.org/(?:copyright/software-license-2002|Consortium/Legal/2002/copyright-software)", re.I), "W3C"),
    # OGC Software License, Version 1.0 — SPDX "OGC-1.0" — e.g. ssn.
    (re.compile(r"(?:opengeospatial|ogc)\.org/ogc/software", re.I), "OGC-1.0"),
    # Open Data Commons (data licenses; SPDX ids exist for all three).
    (re.compile(r"opendatacommons\.org/licenses/odbl"), "ODbL-1.0"),
    (re.compile(r"opendatacommons\.org/licenses/pddl"), "PDDL-1.0"),
    (re.compile(r"opendatacommons\.org/licenses/by"), "ODC-By-1.0"),
    # RDFLicense dataset URIs (purl.org/NET/rdflicense/<name>) — restrictive first.
    (re.compile(r"rdflicense/cc-by-nc-nd(\d\.\d)", re.I), "CC-BY-NC-ND-{v}"),
    (re.compile(r"rdflicense/cc-by-nc-sa(\d\.\d)", re.I), "CC-BY-NC-SA-{v}"),
    (re.compile(r"rdflicense/cc-by-nc(\d\.\d)", re.I), "CC-BY-NC-{v}"),
    (re.compile(r"rdflicense/cc-by-nd(\d\.\d)", re.I), "CC-BY-ND-{v}"),
    (re.compile(r"rdflicense/cc-by-sa(\d\.\d)", re.I), "CC-BY-SA-{v}"),
    (re.compile(r"rdflicense/cc-by(\d\.\d)", re.I), "CC-BY-{v}"),
    (re.compile(r"rdflicense/(?:cc-?zero|cc0)", re.I), "CC0-1.0"),
    (re.compile(r"rdflicense/apache2\.0", re.I), "Apache-2.0"),
    (re.compile(r"rdflicense/mit1\.0", re.I), "MIT"),
    (re.compile(r"rdflicense/gpl3\.0", re.I), "GPL-3.0-only"),
    (re.compile(r"rdflicense/odbl1\.0", re.I), "ODbL-1.0"),
    # License-catalogue URLs that carry the SPDX id (or a close token) verbatim.
    (re.compile(r"spdx\.org/licenses/([A-Za-z0-9+.\-]+?)(?:\.html|\.json|/|\Z)"), "{v}"),
    (re.compile(r"dalicc\.net/licenselibrary/([A-Za-z0-9+.\-]+)"), "{v}"),
)

# A Creative Commons deed named in free text ("… (CC BY-NC-SA 3.0)", "CC-BY 4.0"),
# used as a last resort when no URL/label matched. Captures the modifier and version.
_CC_TEXT = re.compile(
    r"\bcc[ \-]?by(?P<mod>(?:[ \-](?:nc|nd|sa)){0,2})[ \-]?(?P<ver>\d\.\d)\b", re.I
)

# Free-text label (lowercased, punctuation-normalized) → SPDX.
_LABEL_TO_SPDX: dict[str, str] = {
    "cc0": "CC0-1.0", "cc0 1.0": "CC0-1.0", "public domain": "CC0-1.0",
    "cc by 4.0": "CC-BY-4.0", "cc-by 4.0": "CC-BY-4.0", "cc by": "CC-BY-4.0",
    "cc by 3.0": "CC-BY-3.0", "cc by 2.5": "CC-BY-2.5", "cc by 2.0": "CC-BY-2.0",
    "cc by-sa 4.0": "CC-BY-SA-4.0", "cc by sa 4.0": "CC-BY-SA-4.0",
    "cc by-sa 3.0": "CC-BY-SA-3.0",
    # Spelled-out Creative Commons names (the deed's own title text).
    "creative commons attribution 4.0 international": "CC-BY-4.0",
    "creative commons attribution 4.0": "CC-BY-4.0",
    "creative commons attribution 3.0 unported": "CC-BY-3.0",
    "creative commons attribution 3.0": "CC-BY-3.0",
    "creative commons attribution-sharealike 4.0 international": "CC-BY-SA-4.0",
    "creative commons attribution-sharealike 4.0": "CC-BY-SA-4.0",
    "creative commons attribution share alike 4.0": "CC-BY-SA-4.0",
    "mit": "MIT", "mit license": "MIT",
    "apache 2.0": "Apache-2.0", "apache-2.0": "Apache-2.0", "apache license 2.0": "Apache-2.0",
    "bsd-3-clause": "BSD-3-Clause", "bsd 3 clause": "BSD-3-Clause",
    "gpl 3.0": "GPL-3.0-only", "gpl-3.0": "GPL-3.0-only",
    "gpl-3.0-only": "GPL-3.0-only",
    "gpl-3.0-or-later": "GPL-3.0-or-later", "gpl 3.0 or later": "GPL-3.0-or-later",
    "gplv3+": "GPL-3.0-or-later",
    "w3c software notice and license": "W3C", "w3c software license": "W3C",
    "w3c software notice and license 2002": "W3C", "w3c": "W3C",
    "ogc software license": "OGC-1.0", "ogc software license 1.0": "OGC-1.0",
    "ogc software notice": "OGC-1.0",
}

# Versioned/less-common SPDX ids the URL table emits only via a {v} template, listed
# here so a value already in that SPDX form still passes through.
_EXTRA_SPDX: frozenset[str] = frozenset(
    f"CC-BY-{mod}{v}"
    for mod in ("", "SA-", "NC-", "NC-SA-", "NC-ND-", "ND-")
    for v in ("1.0", "2.0", "2.5", "3.0", "4.0")
) | frozenset({"ODC-By-1.0", "ODbL-1.0", "PDDL-1.0", "BSD-4-Clause"})

# SPDX ids we recognize (so a value already in SPDX form passes through). Templated
# ({v}) URL entries are excluded here and covered by _EXTRA_SPDX instead.
_KNOWN_SPDX: frozenset[str] = frozenset(
    list(_LABEL_TO_SPDX.values())
    + [s for _, s in _URL_TO_SPDX if "{v}" not in s]
) | _EXTRA_SPDX


def _cc_from_text(s: str) -> str | None:
    """A CC deed named in free prose → its SPDX id, or None."""
    m = _CC_TEXT.search(s)
    if not m:
        return None
    mods = [p.upper() for p in re.split(r"[ \-]+", m.group("mod")) if p]
    suffix = "".join(f"-{p}" for p in mods)
    return f"CC-BY{suffix}-{m.group('ver')}"


def canonicalize_license(raw: str | None) -> str | None:
    """Map a declared license (URL, label, or SPDX id) to a canonical SPDX id, or
    None if unrecognized. Permission-neutral: an NC/ND/SA license maps to its real
    SPDX id just like a permissive one — the allowlist decision is separate."""
    if not raw:
        return None
    s = raw.strip()
    if not s:
        return None
    # Already an SPDX id we know?
    if s in _KNOWN_SPDX:
        return s
    for pat, spdx in _URL_TO_SPDX:
        m = pat.search(s)
        if m:
            return spdx.format(v=m.group(1)) if "{v}" in spdx else spdx
    key = re.sub(r"\s+", " ", s.lower().replace("_", " ").replace("/", " ")).strip()
    if key in _LABEL_TO_SPDX:
        return _LABEL_TO_SPDX[key]
    # Last resort: a CC deed named inside free text ("… (CC BY 3.0)").
    return _cc_from_text(s)


def compliant_license_set() -> set[str]:
    return {x.strip() for x in get_settings().compliant_licenses.split(",") if x.strip()}


def effective_license(
    content_license: str | None, declared_license: str | None,
) -> tuple[str | None, str | None, bool]:
    """Resolve compliance from the content license plus a contributor's declared
    overlay (#364 Add-Ontology flow). Returns (content_spdx, declared_spdx,
    license_compliant).

    The overlay fills an ABSENCE only: if the content declares ANY license — whether
    recognized-and-non-compliant (e.g. CC-BY-NC) OR present-but-unrecognized
    (a proprietary URL, "All rights reserved", an unmapped label) — that license
    decides on its own and the contributor's overlay cannot launder it; only such a
    license canonicalizing into the allowlist passes. The overlay applies solely
    when the content declares NO license at all. An empty allowlist disables the gate.
    """
    allow = compliant_license_set()
    content_spdx = canonicalize_license(content_license)
    declared_spdx = canonicalize_license(declared_license)
    if not allow:
        return content_spdx, declared_spdx, True
    # A license declared in the content (even one we can't map to SPDX) is "present",
    # not an absence — so an unrecognized string holds and can't be overridden.
    if content_license and content_license.strip():
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


def is_newly_held(prev_status: str, new_status: str) -> bool:
    """True iff this index run is the FIRST time a version is held for review — the
    transition ``* -> needs_review`` where it was not already ``needs_review``.

    The owner "action needed" email keys off this so a re-index of an already-held
    version does not re-nag the contributor. It is a standalone predicate (not
    inlined at the call site) so the re-index-doesn't-re-email invariant is testable
    without standing up the Celery task."""
    return new_status == "needs_review" and prev_status != "needs_review"


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


def reevaluate_from_signals(
    *, license_raw: str | None, declared_license: str | None,
    triple_count: int | None, title: str | None, min_triples: int,
    current_status: str = "needs_review",
) -> tuple[str | None, bool, str, list[str]]:
    """Honest re-run of the quality gate on a held version from its STORED signals —
    the immutable content license (`license_raw`, SHA-256-addressed) overlaid with an
    optional contributor-asserted `declared_license`, no store re-read. Returns
    ``(effective_spdx, license_compliant, new_status, reasons)``; the caller assigns
    the first two onto the version and flips its status when `new_status == "ready"`.

    Shared by the owner reevaluate endpoint and the admin bulk re-check so both apply
    identical gate semantics — the overlay fills a content-license ABSENCE only
    (anti-laundering) and `decide_publish_status` never demotes a `ready` version.
    This is the honest re-check, NOT the admin publish override (which ignores the
    gate)."""
    content_spdx, _, lic_ok = effective_license(license_raw, declared_license)
    new_status, reasons = decide_publish_status(
        current_status, license_compliant=lic_ok, triple_count=triple_count,
        title=title, min_triples=min_triples,
    )
    return content_spdx, lic_ok, new_status, reasons
