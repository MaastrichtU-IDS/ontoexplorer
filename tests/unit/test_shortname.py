"""Tests for the shortname inference + uniqueifier."""
from __future__ import annotations

import pytest

from ontoexplorer.modules.ingestion.shortname import (
    canonicalize_ontology_iri,
    find_ontology_by_canonical_iri,
    infer_shortname_from_iri,
    unique_shortname,
)


def test_infer_strips_trailing_slash():
    assert infer_shortname_from_iri("http://example.org/pets/") == "pets"


def test_infer_strips_fragment():
    assert infer_shortname_from_iri("http://www.w3.org/2004/02/skos/core#") == "core"


def test_infer_strips_owl_extension():
    assert infer_shortname_from_iri(
        "http://purl.obolibrary.org/obo/go.owl",
    ) == "go"


def test_infer_strips_ttl_extension():
    assert infer_shortname_from_iri(
        "https://schema.org/version/latest/schemaorg-current-https.ttl",
    ) == "schemaorg-current-https"


def test_infer_lowercases_uppercase_segments():
    assert infer_shortname_from_iri("https://w3id.org/SULO/") == "sulo"


def test_infer_returns_none_for_empty():
    assert infer_shortname_from_iri("") is None


def test_infer_returns_none_for_segment_too_short():
    # Single-character IRI segment doesn't satisfy `^[a-z0-9][a-z0-9_-]{0,62}[a-z0-9]$`.
    assert infer_shortname_from_iri("http://example.org/a") is None


def test_infer_collapses_invalid_runs_to_single_hyphen():
    assert infer_shortname_from_iri("http://example.org/foo!!!bar") == "foo-bar"


def test_infer_strips_leading_trailing_hyphens():
    assert infer_shortname_from_iri("http://example.org/-foo-") == "foo"


def test_infer_handles_dcterms_style():
    assert infer_shortname_from_iri("http://purl.org/dc/terms/") == "terms"


# ── canonicalize_ontology_iri (#250) ───────────────────────────────────────────

def test_canon_strips_trailing_slash():
    assert canonicalize_ontology_iri("https://w3id.org/sulo/") == "https://w3id.org/sulo"


def test_canon_strips_trailing_fragment():
    # 22-rdf-syntax-ns vs 22-rdf-syntax-ns# → same identity.
    a = canonicalize_ontology_iri("http://www.w3.org/1999/02/22-rdf-syntax-ns#")
    b = canonicalize_ontology_iri("http://www.w3.org/1999/02/22-rdf-syntax-ns")
    assert a == b == "http://www.w3.org/1999/02/22-rdf-syntax-ns"


def test_canon_file_at_namespace_root_collapses():
    # SULO 0.2.0 declared the file URL as its owl:Ontology IRI.
    assert canonicalize_ontology_iri("https://w3id.org/sulo/sulo.ttl") == "https://w3id.org/sulo"


def test_canon_sulo_variants_converge():
    assert (canonicalize_ontology_iri("https://w3id.org/sulo/sulo.ttl")
            == canonicalize_ontology_iri("https://w3id.org/sulo/"))


def test_canon_leaves_shared_registry_root_untouched():
    # /obo/ hosts many distinct ontologies; stem (caro) != parent (obo) → no collapse.
    assert (canonicalize_ontology_iri("http://purl.obolibrary.org/obo/caro.owl")
            == "http://purl.obolibrary.org/obo/caro.owl")


def test_canon_distinct_files_stay_distinct():
    assert (canonicalize_ontology_iri("http://www.ontologydesignpatterns.org/cp/owl/situation.owl")
            != canonicalize_ontology_iri("http://www.ontologydesignpatterns.org/cp/owl/sequence.owl"))


def test_canon_empty_passthrough():
    assert canonicalize_ontology_iri("") == ""


# The test engine is session-scoped (committed rows persist across function-scoped
# db_sessions), so each DB test below uses a unique IRI base to avoid cross-test
# canonical collisions.

@pytest.mark.anyio
async def test_find_by_canonical_matches_file_at_ns_root(db_session):
    from ontoexplorer.models.db import Ontology
    row = Ontology(iri="https://canon.test/fileroot/", shortname="canon-fileroot")
    db_session.add(row)
    await db_session.commit()
    # A later ingest declaring the file URL finds the existing clean row.
    found = await find_ontology_by_canonical_iri(db_session, "https://canon.test/fileroot/fileroot.ttl")
    assert found is not None and found.id == row.id


@pytest.mark.anyio
async def test_find_by_canonical_matches_fragment_variant(db_session):
    from ontoexplorer.models.db import Ontology
    row = Ontology(iri="https://canon.test/frag/ns", shortname="canon-frag")
    db_session.add(row)
    await db_session.commit()
    found = await find_ontology_by_canonical_iri(db_session, "https://canon.test/frag/ns#")
    assert found is not None and found.id == row.id


@pytest.mark.anyio
async def test_find_by_canonical_no_false_match_on_registry_root(db_session):
    from ontoexplorer.models.db import Ontology
    db_session.add(Ontology(iri="https://canon.test/reg/caro.owl", shortname="canon-caro"))
    await db_session.commit()
    # A different file under the same registry root must NOT match.
    found = await find_ontology_by_canonical_iri(db_session, "https://canon.test/reg/ceph.owl")
    assert found is None


@pytest.mark.anyio
async def test_find_by_canonical_excludes_self(db_session):
    from ontoexplorer.models.db import Ontology
    row = Ontology(iri="https://canon.test/selfonly/selfonly.ttl", shortname="canon-selfonly")
    db_session.add(row)
    await db_session.flush()
    found = await find_ontology_by_canonical_iri(
        db_session, "https://canon.test/selfonly/selfonly.ttl", exclude_id=row.id)
    assert found is None


@pytest.mark.anyio
async def test_unique_shortname_returns_candidate_when_free(db_session):
    name = await unique_shortname(db_session, "neverseen")
    assert name == "neverseen"


@pytest.mark.anyio
async def test_unique_shortname_suffixes_on_collision(db_session):
    from ontoexplorer.models.db import Ontology

    db_session.add(Ontology(iri="http://example.org/conflict/", shortname="conflict"))
    await db_session.commit()

    name = await unique_shortname(db_session, "conflict")
    assert name == "conflict-2"


@pytest.mark.anyio
async def test_unique_shortname_keeps_climbing_until_free(db_session):
    from ontoexplorer.models.db import Ontology

    for n in (None, "-2", "-3"):
        suffix = n or ""
        db_session.add(Ontology(
            iri=f"http://example.org/x{suffix}/",
            shortname=f"x{suffix}",
        ))
    await db_session.commit()
    name = await unique_shortname(db_session, "x")
    assert name == "x-4"


@pytest.mark.anyio
async def test_unique_shortname_exclude_id_lets_row_keep_its_own_name(db_session):
    from ontoexplorer.models.db import Ontology

    row = Ontology(iri="http://example.org/self/", shortname="self")
    db_session.add(row)
    await db_session.flush()
    name = await unique_shortname(db_session, "self", exclude_id=row.id)
    assert name == "self"
