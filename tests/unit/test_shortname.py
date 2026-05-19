"""Tests for the shortname inference + uniqueifier."""
from __future__ import annotations

import pytest

from ontoexplorer.modules.ingestion.shortname import (
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
