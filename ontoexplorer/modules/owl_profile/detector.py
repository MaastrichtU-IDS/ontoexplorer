"""OWL 2 profile detection via the native horned-profile checker (py-horned-owl).

Replaces the previous pyowl2_profiles detector, which scanned the ontology as
RDF/quads and **hung** `build_index` on the largest ontologies (Uberon 26k
classes, MONDO 63k) — so those never reached `ready` and #148 had to gate
detection off above a class-count threshold (#149).

horned-profile runs over the horned-owl object model instead, so it is fast at
every size: on MONDO (243 MB RDF/XML, 63k classes) load + all four profile
checks complete in ~80 s, versus pyowl2_profiles running indefinitely.

**Load fidelity.** The ontology is parsed into the horned-owl model from its
stored serialization. Native OWL formats (functional/`ofn`, OWL-XML/`owx`,
`obo`) load fully; for RDF-based ontologies (RDF/XML, Turtle) horned-owl's RDF
reader can drop some complex axioms (see the reasoner-service note about
`owl:AllDisjointClasses`), so violation counts may slightly under-report for
those. That is inherent to any model-based checker and an acceptable trade for
finally classifying the ontologies that previously had no profile at all.
"""
from __future__ import annotations

import re

import structlog

_log = structlog.get_logger("ontoexplorer.owl_profile")

# Order mirrors the historical pyowl2_profiles PROFILE_NAMES so downstream
# payloads/UI are unchanged.
PROFILE_NAMES: tuple[str, ...] = ("el", "rl", "ql", "dl")

# lowercase key -> the profile name horned-profile.check_profile expects.
_CHECK = {"el": "EL", "rl": "RL", "ql": "QL", "dl": "DL"}

# our stored `version.format` -> horned-owl serialization literal. None means
# "let horned-owl auto-detect" (it tries each parser until one succeeds), used
# for formats without a direct mapping (e.g. turtle/ntriples).
_FORMAT_MAP: dict[str, str | None] = {
    "obo": "obo",
    "ofn": "ofn", "functional": "ofn", "owl-functional": "ofn", "func": "ofn",
    "owx": "owx", "owl-xml": "owx", "owlxml": "owx", "owlx": "owx",
    "omn": "omn", "manchester": "omn",
    "owl": "rdf", "rdf": "rdf", "rdfxml": "rdf", "rdf-xml": "rdf", "xml": "rdf",
}

# Per profile, keep a bounded sample of full violation objects (the histogram
# below counts them all, so `total_violations` and the per-type breakdown stay
# exact). Without this a profile with tens of thousands of violations — MONDO's
# RL check finds ~40k — would bloat the Redis payload. The UI shows the first 10.
_SAMPLE_LIMIT = 25

_IRI_RE = re.compile(r"<(https?://[^>]+)>")
# Shorten `<http://…/Local>` / `<http://…#Local>` to `Local` for readable details.
_SHORTEN_RE = re.compile(r"<[^>]*[/#]([^/#>]+)>")


def _shorten(text: str) -> str:
    return _SHORTEN_RE.sub(r"\1", text)


def _serialize_violation(v: object) -> dict:
    """Map a horned-profile Violation to the payload shape the UI expects
    ({axiom_type, subject_iri, details, manchester}). `manchester` is left empty
    — the horned-owl model isn't rendered to Manchester tokens here — so the UI
    falls back to `details` (the offending axiom, IRIs shortened to local names).
    """
    axiom_type = type(v).__name__
    axiom_str = ""
    try:
        axiom = getattr(v, "axiom", None)
        axiom_str = str(axiom) if axiom is not None else str(v)
    except Exception:
        axiom_str = str(v)
    subject_iri = ""
    m = _IRI_RE.search(axiom_str)
    if m:
        subject_iri = m.group(1)
    return {
        "axiom_type": axiom_type,
        "subject_iri": subject_iri,
        "details": _shorten(axiom_str)[:300],
        "manchester": [],
    }


def _load_ontology(content: str | bytes, fmt: str | None):
    import pyhornedowl

    text = (
        content.decode("utf-8", errors="replace")
        if isinstance(content, (bytes, bytearray))
        else content
    )
    ser = _FORMAT_MAP.get((fmt or "").strip().lower())
    if ser:
        return pyhornedowl.open_ontology_from_string(text, ser)
    # Unknown/absent format: let horned-owl try each parser.
    return pyhornedowl.open_ontology_from_string(text)


def detect_profiles(content: str | bytes, fmt: str | None = None) -> dict:
    """Classify *content* against OWL 2 EL/QL/RL/DL.

    Returns `{ "el": {...}, "rl": {...}, "ql": {...}, "dl": {...} }` where each
    entry is `{in_profile, total_violations, violations_by_axiom_type, sample_violations}`.
    Raises on a load/parse failure so the caller can log and skip caching.
    """
    from pyhornedowl import profile as P

    ont = _load_ontology(content, fmt)

    payload: dict = {}
    for key in PROFILE_NAMES:
        report = P.check_profile(ont, _CHECK[key])
        violations = report.violations
        by_type: dict[str, int] = {}
        for v in violations:
            t = type(v).__name__
            by_type[t] = by_type.get(t, 0) + 1
        payload[key] = {
            "in_profile": bool(report.conformant),
            "total_violations": len(violations),
            "violations_by_axiom_type": by_type,
            "sample_violations": [
                _serialize_violation(v) for v in violations[:_SAMPLE_LIMIT]
            ],
        }
    return payload
