"""Gated harvest runner.

Enumerates a ``DiscoverySource``, passes every candidate through the pre-enqueue
admission gate, and (unless ``dry_run``) enqueues admitted candidates for
ingestion with ``source_catalogue`` provenance. Dry-run is the default: it
tallies what *would* be enqueued without ever calling the ingest task.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field

from ontoexplorer.modules.discovery.gate import admit
from ontoexplorer.modules.discovery.source import DiscoverySource
from ontoexplorer.modules.discovery.throttle import RunBudget
from ontoexplorer.modules.federation.client import FederationFetchError

logger = logging.getLogger(__name__)


@dataclass
class HarvestReport:
    source: str
    seen: int = 0
    admitted: int = 0
    enqueued: int = 0
    rejected: dict[str, int] = field(default_factory=dict)  # reason -> count
    errors: list[str] = field(default_factory=list)
    dry_run: bool = True

    def as_dict(self) -> dict:
        return asdict(self)


async def run_harvest(
    db,
    source: DiscoverySource,
    *,
    budget: RunBudget,
    dry_run: bool = True,
    source_catalogue: str,
    groups: list[str],
) -> HarvestReport:
    """Discover, gate and (if not ``dry_run``) enqueue candidates from ``source``."""
    # Imported lazily: jobs.tasks is heavy and (via the harvest_peer task) imports
    # this package, so a top-level import here would be a cycle.
    from ontoexplorer.modules.jobs.tasks import ingest_ontology

    report = HarvestReport(source=source.name, dry_run=dry_run)

    try:
        candidates = await source.discover(limit=budget.remaining)
    except FederationFetchError as exc:
        # Page-fetch errors propagate out of discover(); record, enqueue nothing.
        report.errors.append(f"discover_failed: {exc.reason}")
        logger.warning("harvest_discover_failed source=%s reason=%s", source.name, exc.reason)
        return report

    for candidate in candidates:
        report.seen += 1
        decision = await admit(db, candidate)
        if not decision.admit:
            report.rejected[decision.reason] = report.rejected.get(decision.reason, 0) + 1
            continue
        report.admitted += 1
        if not budget.take():
            break  # budget exhausted
        if dry_run:
            continue
        kind, value = candidate.ingest_target()
        ingest_ontology.delay(
            **{kind: value}, groups=groups,
            source_catalogue=source_catalogue, source_acronym=candidate.acronym,
        )
        report.enqueued += 1

    return report
