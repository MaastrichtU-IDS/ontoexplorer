"""Consistency aggregator: runs all three scopes and assembles a ConsistencyReport.

Per scope:
  1. Resolve MIREOT sources (only fetched once, shared across scopes that need them).
  2. Build the merge .nt file via `merger.build_merge`.
  3. Run Konclude → consistent/inconsistent + unsat IRIs.
  4. Run ROBOT explain ONCE → dict[class_iri -> list[axiom_tokens]] (cap at top 10).
  5. Assemble UnsatisfiableClass entries by looking up each Konclude IRI in the dict.

Failures within one scope (timeout, ROBOT missing, etc.) mark only that scope.
The other scopes still run.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ontoexplorer.clients.robot import (
    RobotConsistencyResult,
    RobotServiceCrashed,
    RobotServiceUnavailable,
    run_robot_consistency,
)
# Konclude wrapper kept around for emergency fallback / comparison runs;
# the active reasoning path now goes through the robot-service HTTP API.
from ontoexplorer.modules.consistency.konclude import (
    KoncludeCrashed,
    KoncludeResult,
    KoncludeTimeout,
    KoncludeUnavailable,
    run_konclude_consistency,
)
import requests as _requests
from ontoexplorer.modules.consistency.merger import build_merge
from ontoexplorer.modules.consistency.mireot_source_resolver import (
    MireotSourceResolveResult,
    fetch_mireot_sources,
)
from ontoexplorer.modules.consistency.robot_explain import (
    RobotExplainTimeout,
    RobotExplainUnavailable,
    explain_unsatisfiability,
)


_MAX_EXPLAINED_PER_SCOPE = 10
_SCOPES = ("host_only", "host_plus_imports", "host_plus_imports_plus_mireot")


@dataclass(frozen=True)
class JustificationAxiom:
    manchester: list                   # list[ManchesterToken] — typed via the library
    source_ontology_iri: str | None = None


@dataclass(frozen=True)
class UnsatisfiableClass:
    iri: str
    label: str | None = None
    justification: list[JustificationAxiom] = field(default_factory=list)


@dataclass
class ScopeResult:
    scope: str
    status: str  # consistent | inconsistent | partial | timeout | error
    unsatisfiable_classes: list[UnsatisfiableClass] = field(default_factory=list)
    mireot_sources_fetched: list[str] = field(default_factory=list)
    mireot_sources_skipped: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    error_message: str | None = None
    # True iff the ontology is GLOBALLY inconsistent (Konclude said inconsistent,
    # classification was skipped, no concrete unsat-class list available). Set
    # BEFORE the synthetic owl:Thing entry is added so it remains a reliable
    # signal even after unsatisfiable_classes is non-empty.
    globally_inconsistent: bool = False


@dataclass
class ConsistencyReport:
    version_id: str
    host_iri: str
    scopes: dict[str, ScopeResult] = field(default_factory=dict)
    job_status: str = "done"
    started_at: str | None = None
    finished_at: str | None = None


def detect_consistency(
    *,
    version_id: str,
    ontology_id: str,
    host_iri: str,
    host_graph_iri: str,
    import_graph_iris: list[str],
    work_dir: Path,
) -> ConsistencyReport:
    """Run all three scopes; return the assembled report."""
    started_at = datetime.now(timezone.utc).isoformat()
    reuse_payload = _load_reuse_payload(version_id)

    # MIREOT sources fetched ONCE (shared between scopes that need them)
    mireot_result: MireotSourceResolveResult = fetch_mireot_sources(
        reuse_payload=reuse_payload,
        out_dir=work_dir / "mireot",
    )

    report = ConsistencyReport(version_id=version_id, host_iri=host_iri)
    for scope in _SCOPES:
        report.scopes[scope] = _run_one_scope(
            scope=scope,
            work_dir=work_dir,
            host_graph_iri=host_graph_iri,
            import_graph_iris=import_graph_iris,
            mireot_paths=list(mireot_result.fetched.values()),
            mireot_fetched_prefixes=sorted(mireot_result.fetched.keys()),
            mireot_skipped_prefixes=list(mireot_result.skipped),
        )

    # If the host_only scope is globally inconsistent (Konclude said inconsistent
    # AND the unsat list is empty — meaning classification was skipped because the
    # ontology has no models), materialize the trivializing entailment
    # `owl:Thing rdfs:subClassOf owl:Nothing` in the inferred graph. This makes
    # the synthetic owl:Nothing node in the class tree the universal ancestor
    # (Protégé's standard rendering for an inconsistent ontology).
    host_only = report.scopes.get("host_only")
    globally_inconsistent = bool(host_only is not None and host_only.globally_inconsistent)
    try:
        _materialize_global_inconsistency(
            ontology_id=ontology_id,
            version_id=version_id,
            present=globally_inconsistent,
        )
    except Exception:
        # Don't fail the consistency check if the graph write fails (e.g. store
        # is read-only because we're inside the api container at test time).
        pass

    report.finished_at = datetime.now(timezone.utc).isoformat()
    report.started_at = started_at
    return report


def _run_one_scope(
    *,
    scope: str,
    work_dir: Path,
    host_graph_iri: str,
    import_graph_iris: list[str],
    mireot_paths: list[Path],
    mireot_fetched_prefixes: list[str],
    mireot_skipped_prefixes: list[str],
) -> ScopeResult:
    t0 = time.monotonic()
    result = ScopeResult(scope=scope, status="error")
    try:
        merge_path = build_merge(
            out_dir=work_dir / scope,
            host_graph_iri=host_graph_iri,
            import_graph_iris=import_graph_iris,
            mireot_source_paths=mireot_paths,
            scope=scope,
        )
    except Exception as exc:
        result.status = "error"
        result.error_message = f"merge failed: {exc}"
        result.elapsed_seconds = time.monotonic() - t0
        return result

    # Active reasoning path: HTTP call to the robot-service container (HermiT).
    # ROBOT returns both the consistency verdict AND the unsat class list in a
    # single invocation (Konclude needed two), so we no longer need a separate
    # explain step here just to enumerate the unsats.
    try:
        rr: RobotConsistencyResult = run_robot_consistency(merge_path)
    except RobotServiceUnavailable as exc:
        result.status = "error"
        result.error_message = f"robot-service unreachable: {exc}"
        result.elapsed_seconds = time.monotonic() - t0
        return result
    except RobotServiceCrashed as exc:
        # Reasoner OOM'd or threw an unhandled exception inside the service.
        # Report `error` rather than guessing a verdict — same defensive
        # principle that fixed the prior Konclude OOM-as-inconsistent bug.
        result.status = "error"
        result.error_message = str(exc)
        result.elapsed_seconds = time.monotonic() - t0
        return result
    except _requests.Timeout as exc:
        result.status = "timeout"
        result.error_message = f"HTTP timeout calling robot-service: {exc}"
        result.elapsed_seconds = time.monotonic() - t0
        return result

    # ROBOT explain ONCE per scope — bulk mode, all unsats explained in one JVM start.
    # Still routed through ROBOT's local subprocess (not the service) for now;
    # folding this into the service is a follow-up.
    explanations: dict[str, list[list]] = {}
    if rr.unsatisfiable_class_iris:
        try:
            explanations = explain_unsatisfiability(
                merge_path,
                max_explanations=_MAX_EXPLAINED_PER_SCOPE,
            )
        except RobotExplainUnavailable:
            explanations = {}
        except RobotExplainTimeout:
            explanations = {}
        except Exception:
            explanations = {}

    # Verdict
    if rr.consistent:
        result.status = "consistent"
    else:
        result.status = "inconsistent"

    # Build UnsatisfiableClass entries from ROBOT's list, looking up justifications
    for iri in rr.unsatisfiable_class_iris:
        axiom_token_lists = explanations.get(iri, [])
        justification = [JustificationAxiom(manchester=a) for a in axiom_token_lists]
        result.unsatisfiable_classes.append(UnsatisfiableClass(
            iri=iri,
            justification=justification,
        ))

    # Globally inconsistent case: ROBOT reported `globally_inconsistent: True`
    # (the "The ontology is inconsistent" message). Set the flag and add a
    # synthetic owl:Thing entry so the class tree's synthetic owl:Nothing node
    # correctly shows owl:Thing as its universal child — the visual realisation
    # of "this ontology has no models, so every entailment, including
    # owl:Thing ⊑ owl:Nothing, holds".
    if rr.globally_inconsistent:
        result.globally_inconsistent = True
        result.unsatisfiable_classes.append(UnsatisfiableClass(
            iri="http://www.w3.org/2002/07/owl#Thing",
            label="owl:Thing",
            justification=[],
        ))

    # MIREOT bookkeeping for the relevant scope
    if scope == "host_plus_imports_plus_mireot":
        result.mireot_sources_fetched = mireot_fetched_prefixes
        result.mireot_sources_skipped = mireot_skipped_prefixes
        if result.status == "consistent" and mireot_skipped_prefixes:
            # Sources were skipped — coverage is partial, not full
            result.status = "partial"

    result.elapsed_seconds = time.monotonic() - t0
    return result


def _materialize_global_inconsistency(
    *,
    ontology_id: str,
    version_id: str,
    present: bool,
) -> None:
    """Add or remove `owl:Thing rdfs:subClassOf owl:Nothing` in the consistency-inferred graph.

    Adding the trivializing entailment is the materialized form of "this ontology
    has no models" — every classical entailment, including this one, holds. Removing
    it (when consistency is restored on a re-run) keeps the graph clean.

    We use a SEPARATE named graph (`urn:ontology:{oid}:{vid}:consistency-inferred`)
    rather than ELK's `:inferred` graph because the reasoning task does
    `remove_graph + bulk_load` and would clobber our triple every time it re-runs.
    The `/inferred` API endpoint and SPARQL queries should UNION both graphs.

    pyoxigraph's `store.add` is idempotent on duplicates; `store.remove` is a no-op
    when the quad isn't present. Both are safe to call unconditionally.
    """
    import pyoxigraph
    from ontoexplorer.clients.oxigraph import consistency_inferred_graph_iri, get_store

    store = get_store()
    graph_uri = consistency_inferred_graph_iri(ontology_id, version_id)
    named = pyoxigraph.NamedNode(graph_uri)
    quad = pyoxigraph.Quad(
        pyoxigraph.NamedNode("http://www.w3.org/2002/07/owl#Thing"),
        pyoxigraph.NamedNode("http://www.w3.org/2000/01/rdf-schema#subClassOf"),
        pyoxigraph.NamedNode("http://www.w3.org/2002/07/owl#Nothing"),
        named,
    )
    # Make sure the named graph exists before adding; add_graph is a no-op if present.
    try:
        store.add_graph(named)
    except Exception:
        pass
    if present:
        store.add(quad)
    else:
        try:
            store.remove(quad)
        except Exception:
            pass


def _load_reuse_payload(version_id: str) -> dict:
    """Load the Phase 1 reuse cache for this version."""
    from ontoexplorer.modules.reuse.cache import reuse_cache_key
    from ontoexplorer.modules.search.indexer import _get_redis

    raw = _get_redis().get(reuse_cache_key(version_id))
    if raw is None:
        return {"mireot_terms": [], "imports": []}
    return json.loads(raw)
