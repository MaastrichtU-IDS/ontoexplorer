"""Write and invalidate the per-version FAIR cache (``versions.fair_*``).

``compute_fair_report`` is a pure function of already-durable signals
(owl_profile/reuse/coverage/license*/version_iri + the ontology row + the meta
profile), so the fair_* columns are a derived cache: filled at index time,
set NULL when any input changes, and self-healed on read by the fleet endpoint.
Keeping the signal query here (one place) guarantees the write and the read use
identical inputs.
"""
from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.models.db import Ontology, OntologyMetaProfile, OntologyVersion
from ontoexplorer.modules.fair.fleet import FairScores, scores_from_report
from ontoexplorer.modules.fair.score import build_fair_inputs, compute_fair_report

SIGNAL_COLS = (
    OntologyVersion.id,
    OntologyVersion.ontology_id,
    OntologyVersion.version_iri,
    OntologyVersion.license,
    OntologyVersion.license_compliant,
    OntologyVersion.license_raw,
    OntologyVersion.owl_profile,
    OntologyVersion.reuse,
    OntologyVersion.coverage,
    Ontology.iri,
    Ontology.shortname,
    Ontology.groups,
    Ontology.resolvable,
    Ontology.resolve_detail,
    OntologyMetaProfile.resolved,
)


def signal_query():
    """SELECT of the FAIR signal columns, joined to the ontology + meta profile."""
    return (
        select(*SIGNAL_COLS)
        .join(Ontology, Ontology.id == OntologyVersion.ontology_id)
        .outerjoin(OntologyMetaProfile, OntologyMetaProfile.version_id == OntologyVersion.id)
    )


def inputs_from_row(row):
    return build_fair_inputs(
        ontology_iri=row.iri,
        resolvable=row.resolvable,
        resolve_detail=row.resolve_detail,
        version_iri=row.version_iri,
        shortname=row.shortname,
        groups=row.groups,
        license_raw=row.license_raw,
        license_spdx=row.license,
        license_compliant=row.license_compliant,
        owl_profile=row.owl_profile,
        reuse=row.reuse,
        coverage=row.coverage,
        meta_resolved=row.resolved,
    )


def column_values(scores: FairScores) -> dict:
    """The fair_* column values for a FairScores."""
    return {
        "fair_overall": scores.overall,
        "fair_f": scores.f,
        "fair_a": scores.a,
        "fair_i": scores.i,
        "fair_r": scores.r,
        "fair_checks": scores.checks,
    }


async def compute_and_store_fair(db: AsyncSession, version_id: str) -> FairScores | None:
    """Compute one version's FAIR scores from its durable signals and write the
    fair_* cache. Returns the scores, or None if the version is gone. Does not
    commit — the caller owns the transaction."""
    row = (await db.execute(signal_query().where(OntologyVersion.id == version_id))).first()
    if row is None:
        return None
    scores = scores_from_report(compute_fair_report(inputs_from_row(row)))
    await db.execute(
        update(OntologyVersion).where(OntologyVersion.id == version_id).values(**column_values(scores))
    )
    return scores


async def invalidate_fair(db: AsyncSession, version_id: str) -> None:
    """Null a version's FAIR cache so the fleet endpoint recomputes it on next
    read. Call after any FAIR input changes outside the index task (license
    declare/backfill, owl_profile/reuse refresh). Does not commit."""
    await db.execute(
        update(OntologyVersion)
        .where(OntologyVersion.id == version_id)
        .values(fair_overall=None, fair_f=None, fair_a=None, fair_i=None, fair_r=None, fair_checks=None)
    )
