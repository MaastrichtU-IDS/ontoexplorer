"""Pre-enqueue admission gate for discovered ontology candidates.

Cheap checks that run BEFORE a candidate is enqueued for ingestion, so the
harvest does not spend ingest work on obvious rejects. Check order (first
failing check wins): bad_iri -> no_title -> duplicate -> license_noncompliant.

License rule is intentionally MORE LENIENT than the post-ingest gate
(``is_compliant``/``effective_license``, which hold a present-but-unrecognised
license): here an absent OR unrecognised license is an ABSENCE of proof, not a
violation, so it is admitted and the post-ingest pipeline gate holds it later.
Only a license that canonicalizes to a recognised SPDX id outside a non-empty
allowlist is rejected pre-enqueue.
"""

from __future__ import annotations

from dataclasses import dataclass

from ontoexplorer.modules.discovery.models import Candidate
from ontoexplorer.modules.ingestion.license import canonicalize_license, compliant_license_set
from ontoexplorer.modules.ingestion.shortname import find_ontology_by_canonical_iri


@dataclass(frozen=True)
class AdmissionDecision:
    admit: bool
    reason: str  # "ok" | "duplicate" | "license_noncompliant" | "no_title" | "bad_iri"


def _is_http_url(iri: str) -> bool:
    iri = (iri or "").strip().lower()
    for scheme in ("http://", "https://"):
        if iri.startswith(scheme) and len(iri) > len(scheme):
            return True
    return False


async def admit(db, candidate: Candidate) -> AdmissionDecision:
    """Decide whether ``candidate`` may be enqueued for ingestion."""
    if not _is_http_url(candidate.canonical_iri):
        return AdmissionDecision(False, "bad_iri")
    if not (candidate.title or "").strip():
        return AdmissionDecision(False, "no_title")
    if await find_ontology_by_canonical_iri(db, candidate.canonical_iri) is not None:
        return AdmissionDecision(False, "duplicate")
    allowlist = compliant_license_set()
    if allowlist:
        spdx = canonicalize_license(candidate.license)
        if spdx is not None and spdx not in allowlist:
            return AdmissionDecision(False, "license_noncompliant")
    return AdmissionDecision(True, "ok")
