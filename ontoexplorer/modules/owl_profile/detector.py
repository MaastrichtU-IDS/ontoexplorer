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

_IRI_RE = re.compile(r"<(https?://[^>]+)>")
# Shorten `<http://…/Local>` / `<http://…#Local>` to `Local` for readable details.
_SHORTEN_RE = re.compile(r"<[^>]*[/#]([^/#>]+)>")

# horned-profile Violation subclasses expose the offending thing on different
# attributes. Each str()s usefully: an entity attribute (iri / ope / ap / dp /
# datatype) to a bare IRI, an expression attribute (axiom / ce / dr) to OWL
# functional syntax (e.g. `SubClassOf(<A> ObjectUnionOf(<B> <C>))`). We prefer the
# bare entity IRI (the `UseOfUndeclared*` / reserved / punning violations carry
# only `iri`), then the full axiom for the context-bearing kinds.
_COMPONENT_ATTRS = ("iri", "axiom", "ce", "ope", "dr", "ap", "dp", "datatype")


def _shorten(text: str) -> str:
    return _SHORTEN_RE.sub(r"\1", text)


def _local_name(iri: str) -> str:
    """`http://purl.obolibrary.org/obo/GO_0008150` -> `GO_0008150`."""
    s = iri.rstrip("/#")
    for sep in ("#", "/"):
        if sep in s:
            s = s.rsplit(sep, 1)[-1]
    return s or iri


def _serialize_violation(v: object) -> dict:
    """Map a horned-profile Violation to {axiom_type, subject_iri, details}, naming
    the SPECIFIC offending entity (local name) or axiom (functional syntax, IRIs
    shortened) — not just the generic violation message. Used by the full-report
    CLI (`python -m ontoexplorer.modules.owl_profile.detect`); the cached payload
    keeps only counts (see detect_profiles).
    """
    axiom_type = type(v).__name__
    message = ""
    try:
        message = str(getattr(v, "message", "") or "")
    except Exception:
        message = ""

    focus = ""
    for attr in _COMPONENT_ATTRS:
        comp = getattr(v, attr, None)
        if comp is None:
            continue
        try:
            focus = str(comp).strip()
        except Exception:
            focus = ""
        if focus:
            break

    if focus.startswith(("http://", "https://")) and " " not in focus:
        subject_iri = focus
        details = _local_name(focus)
    else:
        m = _IRI_RE.search(focus)
        subject_iri = m.group(1) if m else ""
        details = _shorten(focus)[:300]
    return {
        "axiom_type": axiom_type,
        "subject_iri": subject_iri,
        "details": details or message,
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


def _by_type(violations) -> dict[str, int]:
    by_type: dict[str, int] = {}
    for v in violations:
        t = type(v).__name__
        by_type[t] = by_type.get(t, 0) + 1
    return by_type


def detect_profiles(content: str | bytes, fmt: str | None = None) -> dict:
    """Classify *content* against OWL 2 EL/QL/RL/DL (cached summary).

    Returns `{ "el": {...}, "rl": {...}, "ql": {...}, "dl": {...} }` where each
    entry is `{in_profile, total_violations, violations_by_axiom_type}`. The
    per-instance violation list is intentionally NOT included — it can be tens of
    thousands of rows (MONDO's RL check ≈ 40k) and would bloat the Redis payload
    read on every page load; the UI shows the type histogram, and the full
    per-entity list is available via `full_violations` / the detect CLI.
    Raises on a load/parse failure so the caller can log and skip caching.
    """
    from pyhornedowl import profile as P

    ont = _load_ontology(content, fmt)
    payload: dict = {}
    for key in PROFILE_NAMES:
        report = P.check_profile(ont, _CHECK[key])
        payload[key] = {
            "in_profile": bool(report.conformant),
            "total_violations": len(report.violations),
            "violations_by_axiom_type": _by_type(report.violations),
        }
    return payload


def full_violations(
    content: str | bytes, fmt: str | None = None,
    profiles: tuple[str, ...] = PROFILE_NAMES,
) -> dict:
    """Like detect_profiles but with EVERY violation serialized (uncapped), for the
    full-report CLI. Not cached. Each entry adds `violations: [...]` naming the
    specific entity/axiom of each violation.
    """
    from pyhornedowl import profile as P

    ont = _load_ontology(content, fmt)
    out: dict = {}
    for key in profiles:
        report = P.check_profile(ont, _CHECK[key])
        out[key] = {
            "in_profile": bool(report.conformant),
            "total_violations": len(report.violations),
            "violations_by_axiom_type": _by_type(report.violations),
            "violations": [_serialize_violation(v) for v in report.violations],
        }
    return out
