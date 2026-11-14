"""Pure FAIR scoring, aligned to the FOOPS! check set.

``compute_fair_report`` turns a :class:`FairInputs` — primitive values already
loaded from ``versions.*`` and the related ``ontology_meta_profiles`` row — into a
19-check report scored per FAIR principle. The function does no I/O: the caller
assembles the inputs (per-ontology endpoint or the fleet aggregate), so the same
scorer serves both without ever touching the store or the network.

Scoring: each check is pass (1.0) / partial (0.5) / graded (a fraction in
[0, 1]); a principle score is the mean of its checks, and the overall score the
mean of the four principle scores. A graded check reads as pass at >= 0.85,
partial at >= 0.50, fail below.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ontoexplorer.modules.meta_profile.registry import ALL_META_ROLES, ROLE_RESOLVED_KEY

# Optional MOD relationship/usage roles excluded from the R4 denominator — they
# are shown in the report but do not count toward metadata completeness.
R4_EXCLUDED_ROLES: frozenset[str] = frozenset({
    "competency_question", "endorsed_by", "relies_on", "similar",
    "generalizes", "specializes", "known_usage", "used_in_project",
})

# Registry tags that satisfy "present in a community registry" (F6).
REGISTRY_TAGS: frozenset[str] = frozenset({"lov", "obo", "obo-foundry", "bioportal"})

PASS, PARTIAL, FAIL = "pass", "partial", "fail"

_PREFIXES: list[tuple[str, str]] = [
    ("http://purl.org/dc/terms/", "dcterms:"),
    ("http://purl.org/dc/elements/1.1/", "dc:"),
    ("http://www.w3.org/2000/01/rdf-schema#", "rdfs:"),
    ("http://www.w3.org/2002/07/owl#", "owl:"),
    ("http://xmlns.com/foaf/0.1/", "foaf:"),
    ("http://www.w3.org/ns/dcat#", "dcat:"),
    ("https://schema.org/", "schema:"),
    ("http://purl.org/vocab/vann/", "vann:"),
    ("https://w3id.org/mod#", "mod:"),
    ("http://purl.org/pav/", "pav:"),
]

ROLE_LABELS: dict[str, str] = {
    "title": "Title", "shortname": "Short name / acronym", "description": "Description",
    "creator": "Creator", "contributor": "Contributor", "publisher": "Publisher",
    "license": "License", "homepage": "Homepage", "version_info": "Version info",
    "version_iri": "Version IRI", "prefix": "Namespace prefix", "namespace_uri": "Namespace URI",
    "created": "Created", "modified": "Modified", "language": "Language", "citation": "Citation",
    "funding": "Funding", "status": "Status", "syntax": "Syntax / representation language",
    "see_also": "See also", "is_defined_by": "Is defined by",
    "competency_question": "Competency question", "endorsed_by": "Endorsed by",
    "relies_on": "Relies on", "similar": "Similar", "generalizes": "Generalizes",
    "specializes": "Specializes", "known_usage": "Known usage", "used_in_project": "Used in project",
}

_RDF_HINTS = ("rdf", "turtle", "ttl", "n-triples", "ntriples", "n3", "json-ld", "ld+json", "owl")


def _short(iri: str) -> str:
    for base, pfx in _PREFIXES:
        if iri.startswith(base):
            return pfx + iri[len(base):]
    return iri


@dataclass
class FairInputs:
    """Primitive signal values already persisted for one version."""
    ontology_iri: str | None = None
    resolvable: bool | None = None
    resolve_content_type: str | None = None
    version_iri: str | None = None
    shortname: str | None = None
    groups: list[str] = field(default_factory=list)
    license_raw: str | None = None
    license_spdx: str | None = None
    license_compliant: bool = False
    owl_profile: dict | None = None
    reuse: dict | None = None
    coverage: dict | None = None
    meta_resolved: dict = field(default_factory=dict)


@dataclass
class FairCheck:
    id: str
    principle: str
    name: str
    status: str
    score: float
    evidence: str
    panel: str
    tests: list[tuple[str, str]] = field(default_factory=list)
    detail: dict | None = None


@dataclass
class PrincipleScore:
    principle: str
    score: float
    checks: list[FairCheck]


@dataclass
class FairReport:
    overall: float
    verdict: str
    principles: list[PrincipleScore]
    n_checks: int
    n_passed: float


# ── builders ──────────────────────────────────────────────────────────────────

def build_fair_inputs(
    *, ontology_iri, resolvable, resolve_detail, version_iri, shortname, groups,
    license_raw, license_spdx, license_compliant, owl_profile, reuse, coverage,
    meta_resolved,
) -> FairInputs:
    """Assemble :class:`FairInputs` from already-loaded ORM values. Pure; no I/O."""
    ct = None
    if isinstance(resolve_detail, dict):
        ct = resolve_detail.get("content_type") or resolve_detail.get("rdf_content_type")
    return FairInputs(
        ontology_iri=ontology_iri,
        resolvable=resolvable,
        resolve_content_type=ct,
        version_iri=version_iri,
        shortname=shortname,
        groups=list(groups or []),
        license_raw=license_raw,
        license_spdx=license_spdx,
        license_compliant=bool(license_compliant),
        owl_profile=owl_profile,
        reuse=reuse,
        coverage=coverage,
        meta_resolved=dict(meta_resolved or {}),
    )


# ── helpers ───────────────────────────────────────────────────────────────────

def _graded_status(frac: float) -> str:
    return PASS if frac >= 0.85 else PARTIAL if frac >= 0.50 else FAIL


def _tier(owl_profile: dict | None) -> str | None:
    if not owl_profile:
        return None
    lang = owl_profile.get("language")
    if isinstance(lang, dict):
        return lang.get("tier")
    return lang if isinstance(lang, str) else None


def _coverage_fraction(coverage: dict | None, key: str) -> tuple[float, int, int]:
    """(fraction, matched, total) over all entity types for ``with_label`` / ``with_definition``."""
    if not coverage:
        return 0.0, 0, 0
    total = matched = 0
    for bucket in (coverage.get("by_type") or {}).values():
        total += int(bucket.get("total", 0))
        matched += int(bucket.get(key, 0))
    return (matched / total if total else 0.0), matched, total


def _meta_filled(meta: dict, role: str) -> bool:
    return bool(meta.get(ROLE_RESOLVED_KEY.get(role, role)))


# ── per-principle check builders ──────────────────────────────────────────────

def _findable(inp: FairInputs) -> list[FairCheck]:
    m = inp.meta_resolved
    has_reg = bool(set(g.lower() for g in inp.groups) & REGISTRY_TAGS)
    return [
        FairCheck("F1", "F", "Globally unique, stable identifier",
                  PASS if inp.ontology_iri else FAIL, 1.0 if inp.ontology_iri else 0.0,
                  "Canonical ontology IRI present." if inp.ontology_iri else "No canonical ontology IRI.",
                  "identity",
                  [("Canonical ontology IRI", inp.ontology_iri or "— none —")]),
        FairCheck("F2", "F", "Ontology IRI resolves",
                  PASS if inp.resolvable else FAIL, 1.0 if inp.resolvable else 0.0,
                  "IRI resolves." if inp.resolvable else "IRI does not resolve or not yet checked.",
                  "resolvable",
                  [("Result", "resolves" if inp.resolvable else "not resolvable / unchecked")]),
        FairCheck("F3", "F", "Version IRI declared",
                  PASS if inp.version_iri else FAIL, 1.0 if inp.version_iri else 0.0,
                  "owl:versionIRI present." if inp.version_iri else "No version IRI.",
                  "metadata",
                  [("Predicate", "owl:versionIRI"), ("Found", inp.version_iri or "— none —")]),
        _title_desc(m),
        FairCheck("F5", "F", "Prefix declared",
                  PASS if (m.get("prefix") or inp.shortname) else FAIL,
                  1.0 if (m.get("prefix") or inp.shortname) else 0.0,
                  "Namespace prefix available." if (m.get("prefix") or inp.shortname) else "No prefix.",
                  "metadata",
                  [("Predicate", "vann:preferredNamespacePrefix (else inferred)"),
                   ("Found", m.get("prefix") or inp.shortname or "— none —")]),
        FairCheck("F6", "F", "Registry presence",
                  PASS if has_reg else FAIL, 1.0 if has_reg else 0.0,
                  "Listed in a community registry." if has_reg else "Not in a tracked registry.",
                  "tags",
                  [("Registries checked", "LOV · OBO Foundry · BioPortal"),
                   ("Member of", ", ".join(inp.groups) or "— none —")]),
    ]


def _title_desc(m: dict) -> FairCheck:
    has_t, has_d = bool(m.get("title")), bool(m.get("description"))
    ok = has_t and has_d
    return FairCheck(
        "F4", "F", "Title & description present",
        PASS if ok else FAIL, 1.0 if ok else 0.0,
        "Both declared." if ok else ("Missing description." if has_t else "Missing title." if has_d else "Missing title & description."),
        "metadata",
        [("Title (any of)", " ".join(_short(i) for i in ALL_META_ROLES["title"]) + (" → found" if has_t else " → none")),
         ("Description (any of)", " ".join(_short(i) for i in ALL_META_ROLES["description"]) + (" → found" if has_d else " → none"))],
    )


def _accessible(inp: FairInputs) -> list[FairCheck]:
    ct = (inp.resolve_content_type or "").lower()
    rdf_conneg = bool(inp.resolvable) and any(h in ct for h in _RDF_HINTS)
    a1_status = PASS if rdf_conneg else PARTIAL if inp.resolvable else FAIL
    a1_score = 1.0 if rdf_conneg else 0.5 if inp.resolvable else 0.0
    open_proto = bool(inp.ontology_iri and inp.ontology_iri.lower().startswith(("http://", "https://")))
    return [
        FairCheck("A1", "A", "Content negotiation to RDF", a1_status, a1_score,
                  "Serves RDF on Accept." if rdf_conneg else "Resolves; RDF content type unconfirmed." if inp.resolvable else "Not retrievable.",
                  "resolvable",
                  [("Accept requested", "text/turtle, application/rdf+xml, application/n-triples, application/ld+json"),
                   ("Served", inp.resolve_content_type or "— unknown —")]),
        FairCheck("A2", "A", "Open protocol",
                  PASS if open_proto else FAIL, 1.0 if open_proto else 0.0,
                  "Retrievable over HTTP(S)." if open_proto else "No HTTP(S) identifier.",
                  "resolvable", [("Scheme", "https" if (inp.ontology_iri or "").startswith("https") else "http" if open_proto else "—")]),
        FairCheck("A3", "A", "Metadata persists if source dies", PASS, 1.0,
                  "Platform guarantee — the artifact is retained and served independent of the source URL.",
                  "mod-api",
                  [("Mechanism", "original upload mirrored in object storage"),
                   ("Served via", "MOD-API distributions, independent of the source URL"),
                   ("Scope", "guarantee for every retained version — not a probe")]),
    ]


def _interoperable(inp: FairInputs) -> list[FairCheck]:
    tier = _tier(inp.owl_profile)
    op = inp.owl_profile or {}
    has_profiles = any(k in op for k in ("el", "ql", "rl", "dl"))
    if has_profiles:
        i2s, i2sc, i2ev = PASS, 1.0, _nearest_profile(op)
    elif op.get("profiles_unavailable"):
        i2s, i2sc, i2ev = PARTIAL, 0.5, "Strict parser could not compute profiles; language tier retained."
    else:
        i2s, i2sc, i2ev = FAIL, 0.0, "No OWL 2 profile computed."

    reuse = inp.reuse or {}
    reused = reuse.get("term_iri_reuse") or {}
    n_sources = len(reused)
    imports = reuse.get("imports") or []
    mappings = reuse.get("mappings") or {}
    n_map = sum(len(v or []) for v in mappings.values()) + len(reuse.get("mireot_terms") or [])
    if imports:
        i4s, i4sc, i4ev = PASS, 1.0, f"{len(imports)} import(s) in the closure."
    elif n_map:
        i4s, i4sc, i4ev = PARTIAL, 0.5, f"{n_map} external mapping(s)/MIREOT term(s); no owl:imports."
    else:
        i4s, i4sc, i4ev = FAIL, 0.0, "No imports or external references."
    return [
        FairCheck("I1", "I", "Formal language tier",
                  PASS if tier else FAIL, 1.0 if tier else 0.0,
                  f"Classified as {tier}." if tier else "No language tier.",
                  "profile", [("Method", "store-based SPARQL tier classification"), ("Tier", tier or "—")]),
        FairCheck("I2", "I", "OWL 2 profile computed", i2s, i2sc, i2ev, "profile",
                  [("Method", "py-horned-owl profile validation"),
                   ("Result", _nearest_profile(op) if has_profiles else "unavailable")]),
        FairCheck("I3", "I", "Reuses established vocabularies",
                  PASS if n_sources else FAIL, 1.0 if n_sources else 0.0,
                  f"Reuses {n_sources} external source(s)." if n_sources else "No external vocabulary reuse detected.",
                  "reuse", [("Method", "term-IRI namespaces classified via bioregistry"),
                            ("Reused sources", " ".join(sorted(reused)) or "— none —")]),
        FairCheck("I4", "I", "Qualified cross-references", i4s, i4sc, i4ev, "reuse",
                  [("owl:imports", str(len(imports))),
                   ("Mappings / MIREOT", str(n_map))]),
    ]


def _nearest_profile(op: dict) -> str:
    for p, label in (("el", "OWL 2 EL"), ("ql", "OWL 2 QL"), ("rl", "OWL 2 RL")):
        if (op.get(p) or {}).get("in_profile"):
            return label
    if (op.get("dl") or {}).get("in_profile"):
        return "OWL 2 DL"
    return "OWL 2 Full (outside EL/QL/RL/DL)"


def _reusable(inp: FairInputs) -> list[FairCheck]:
    m = inp.meta_resolved
    has_lic = bool(inp.license_raw or inp.license_spdx)
    if inp.license_spdx and inp.license_compliant:
        r2s, r2sc, r2ev = PASS, 1.0, f"SPDX {inp.license_spdx}; passes the compliance allowlist."
    elif inp.license_spdx:
        r2s, r2sc, r2ev = PARTIAL, 0.5, f"SPDX {inp.license_spdx}; not on the compliance allowlist (NC/ND)."
    else:
        r2s, r2sc, r2ev = FAIL, 0.0, "License not machine-readable (no SPDX id)."

    has_prov = bool(m.get("creators")) or bool(m.get("created") and m.get("publishers"))

    lbl_frac, lbl_m, lbl_t = _coverage_fraction(inp.coverage, "with_label")
    def_frac, def_m, def_t = _coverage_fraction(inp.coverage, "with_definition")

    return [
        FairCheck("R1", "R", "License present",
                  PASS if has_lic else FAIL, 1.0 if has_lic else 0.0,
                  "License asserted." if has_lic else "No license.",
                  "license", [("Predicate (any of)", "dcterms:license  dcterms:rights"),
                              ("Found", inp.license_raw or inp.license_spdx or "— none —")]),
        FairCheck("R2", "R", "Machine-readable & compliant license", r2s, r2sc, r2ev, "license",
                  [("SPDX", inp.license_spdx or "— none —"),
                   ("Compliance allowlist", "pass" if inp.license_compliant else "fail / n-a")]),
        FairCheck("R3", "R", "Provenance metadata",
                  PASS if has_prov else FAIL, 1.0 if has_prov else 0.0,
                  "Creator/date/publisher present." if has_prov else "Insufficient provenance.",
                  "metadata",
                  [("Creator (any of)", " ".join(_short(i) for i in ALL_META_ROLES["creator"]) + (" → ok" if m.get("creators") else " → none")),
                   ("Created", "ok" if m.get("created") else "none"),
                   ("Publisher", "ok" if m.get("publishers") else "none")]),
        _r4(m),
        FairCheck("R5", "R", "Terms carry labels", _graded_status(lbl_frac), lbl_frac,
                  f"{round(lbl_frac * 100)}% have rdfs:label." if lbl_t else "No indexed terms.",
                  "coverage", [("Predicate", "rdfs:label on classes & properties"),
                               ("Coverage", f"{lbl_m} / {lbl_t} = {round(lbl_frac * 100)}%" if lbl_t else "n/a")]),
        FairCheck("R6", "R", "Terms carry definitions", _graded_status(def_frac), def_frac,
                  f"{round(def_frac * 100)}% have a definition." if def_t else "No indexed terms.",
                  "coverage", [("Predicates (any of)", "skos:definition  obo:IAO_0000115  rdfs:comment"),
                               ("Coverage", f"{def_m} / {def_t} = {round(def_frac * 100)}%" if def_t else "n/a")]),
    ]


def _r4(meta: dict) -> FairCheck:
    roles = []
    filled = scored = 0
    for role in ALL_META_ROLES:
        excluded = role in R4_EXCLUDED_ROLES
        is_filled = _meta_filled(meta, role)
        roles.append({
            "role": ROLE_LABELS.get(role, role),
            "predicates": [_short(i) for i in ALL_META_ROLES[role]],
            "filled": is_filled,
            "excluded": excluded,
        })
        if not excluded:
            scored += 1
            if is_filled:
                filled += 1
    frac = filled / scored if scored else 0.0
    return FairCheck(
        "R4", "R", "Recommended metadata completeness", _graded_status(frac), frac,
        f"{filled} of {scored} scored roles filled ({round(frac * 100)}%); "
        f"{len(R4_EXCLUDED_ROLES)} optional MOD roles excluded.",
        "metadata",
        detail={"roles": roles, "scored": scored, "filled": filled, "excluded": len(R4_EXCLUDED_ROLES)},
    )


# ── top-level ─────────────────────────────────────────────────────────────────

def _verdict(overall: float) -> str:
    return "Strong FAIRness" if overall >= 0.85 else "Fair" if overall >= 0.50 else "Weak"


def compute_fair_report(inp: FairInputs) -> FairReport:
    groups = [
        ("F", _findable(inp)),
        ("A", _accessible(inp)),
        ("I", _interoperable(inp)),
        ("R", _reusable(inp)),
    ]
    principles: list[PrincipleScore] = []
    for letter, checks in groups:
        pscore = sum(c.score for c in checks) / len(checks)
        principles.append(PrincipleScore(letter, pscore, checks))
    overall = sum(p.score for p in principles) / len(principles)
    n_passed = sum(c.score for p in principles for c in p.checks)
    n_checks = sum(len(p.checks) for p in principles)
    return FairReport(overall=overall, verdict=_verdict(overall),
                      principles=principles, n_checks=n_checks, n_passed=n_passed)
