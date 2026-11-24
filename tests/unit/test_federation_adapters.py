import json
from pathlib import Path

import pytest

from ontoexplorer.modules.federation.adapters import (
    adapter_for,
    parse_dcat2,
    parse_mod,
)
from ontoexplorer.modules.federation.config import Peer
from ontoexplorer.modules.federation.models import ArtefactRow, CatalogueStatus

FIX = Path(__file__).resolve().parent.parent / "fixtures" / "federation"

OURS = Peer(id="ours", label="OntoExplorer", base_url="https://ontoexplorer.example.org")
AGRO = Peer(
    id="agroportal",
    label="AgroPortal",
    base_url="https://data.agroportal.lirmm.fr",
    mod_path="/mod-api",
    adapter="dcat2",
)


def _load(name: str) -> dict:
    return json.loads((FIX / name).read_text())


def test_models_shape():
    row = ArtefactRow(
        iri="http://x/o",
        acronym="O",
        title="T",
        description="",
        source_landing_url="http://x/o",
        source={"id": "p", "label": "P"},
    )
    assert row.remote is True
    assert row.publisher is None and row.license is None and row.homepage is None
    assert row.source.id == "p" and row.source.label == "P"
    st = CatalogueStatus(id="p", label="P", status="ok", count=3, took_ms=12)
    assert st.model_dump() == {"id": "p", "label": "P", "status": "ok", "count": 3, "took_ms": 12}


def test_parse_mod_fixture():
    rows = parse_mod(_load("ours_artefacts.jsonld"), OURS)
    assert [r.acronym for r in rows] == ["CL", "CLO", "bare"]
    cl = rows[0]
    assert isinstance(cl, ArtefactRow)
    assert cl.iri == "http://purl.obolibrary.org/obo/cl.owl"
    assert cl.title == "Cell Ontology"
    assert cl.description == "An ontology of cell types."
    assert cl.publisher == "http://www.obofoundry.org/"
    assert cl.license == "https://creativecommons.org/licenses/by/4.0/"
    assert cl.homepage == "https://obophenotype.github.io/cell-ontology/"
    assert cl.source_landing_url == "https://obophenotype.github.io/cell-ontology/"
    assert cl.source.id == "ours" and cl.source.label == "OntoExplorer"
    assert cl.remote is True


def test_parse_mod_language_value_and_string_predicates():
    clo = parse_mod(_load("ours_artefacts.jsonld"), OURS)[1]
    assert clo.title == "Cell Line Ontology"
    assert clo.publisher == "OBO Foundry"
    assert clo.license == "https://creativecommons.org/licenses/by/3.0/"
    # no homepage -> fallback to peer MOD artefact URL keyed by acronym
    assert clo.homepage is None
    assert clo.source_landing_url == "https://ontoexplorer.example.org/mod/artefacts/CLO"


def test_member_missing_optionals_still_yields_row():
    bare = parse_mod(_load("ours_artefacts.jsonld"), OURS)[2]
    assert bare.iri == "http://example.org/onto/bare"
    assert bare.title == "Bare Ontology"
    assert bare.acronym == "bare"  # derived from the IRI tail
    assert bare.description == ""
    assert bare.publisher is None and bare.license is None and bare.homepage is None
    assert bare.source_landing_url == "https://ontoexplorer.example.org/mod/artefacts/bare"


def test_member_missing_title_or_iri_is_skipped():
    doc = {
        "@context": {"dcterms": "http://purl.org/dc/terms/"},
        "hydra:member": [
            {"@id": "http://x/a"},
            {"dcterms:title": "No iri"},
            {"@id": "http://x/b", "dcterms:title": "Ok"},
        ],
    }
    rows = parse_mod(doc, OURS)
    assert [r.iri for r in rows] == ["http://x/b"]


def test_parse_dcat2_fixture():
    rows = parse_dcat2(_load("agroportal_artefacts.jsonld"), AGRO)
    # third member has no title -> skipped
    assert [r.acronym for r in rows] == ["PO", "EOL"]
    po, eol = rows
    assert po.title == "Plant Ontology"  # English preferred over first language
    assert po.publisher == "AgroPortal"  # foaf:name of the publisher node
    assert po.license == "https://creativecommons.org/licenses/by/4.0/"
    assert po.homepage == "https://agroportal.lirmm.fr/ontologies/PO"  # dcat:landingPage
    assert po.source_landing_url == "https://agroportal.lirmm.fr/ontologies/PO"
    assert po.source.id == "agroportal" and po.source.label == "AgroPortal"
    assert eol.iri == "http://opendata.inra.fr/EOL/eol"
    assert eol.homepage == "https://www.eol.example.org/"
    assert eol.source_landing_url == "https://www.eol.example.org/"


def test_dcat2_fallback_landing_uses_base_url():
    doc = {
        "@context": {"dcterms": "http://purl.org/dc/terms/", "mod": "https://w3id.org/mod#"},
        "hydra:member": [{"@id": "http://x/a", "mod:acronym": "A", "dcterms:title": "A title"}],
    }
    row = parse_dcat2(doc, AGRO)[0]
    assert row.source_landing_url == "https://data.agroportal.lirmm.fr/mod/artefacts/A"


def test_dcat2_tolerates_dcat_dataset_framing_and_full_iris():
    doc = {
        "http://www.w3.org/ns/dcat#dataset": [
            {
                "@id": "http://x/d1",
                "http://purl.org/dc/terms/title": [{"@value": "Full IRI title"}],
                "http://purl.org/dc/terms/description": [{"@value": "d"}],
                "https://w3id.org/mod#acronym": [{"@value": "FIT"}],
            }
        ]
    }
    rows = parse_dcat2(doc, AGRO)
    assert len(rows) == 1
    assert rows[0].title == "Full IRI title"
    assert rows[0].acronym == "FIT"
    assert rows[0].description == "d"


def test_graph_and_single_member_framings():
    graph_doc = {
        "@context": {"dcterms": "http://purl.org/dc/terms/", "mod": "https://w3id.org/mod#"},
        "@graph": [
            {"@id": "http://x/coll", "@type": "hydra:Collection"},
            {
                "@id": "http://x/a",
                "@type": "mod:SemanticArtefact",
                "dcterms:title": "A",
            },
        ],
    }
    assert [r.iri for r in parse_mod(graph_doc, OURS)] == ["http://x/a"]
    single = {"hydra:member": {"@id": "http://x/s", "dcterms:title": "S"}}
    assert [r.iri for r in parse_mod(single, OURS)] == ["http://x/s"]


@pytest.mark.parametrize(
    "doc",
    [
        {},
        [],
        None,
        "nope",
        42,
        {"hydra:member": "not-a-list"},
        {"hydra:member": [None, 3, "x", []]},
        {"hydra:member": [{"@id": 5, "dcterms:title": {"@value": {"x": 1}}}]},
        {"@graph": None},
    ],
)
@pytest.mark.parametrize("parser", [parse_mod, parse_dcat2])
def test_malformed_docs_yield_empty_and_never_raise(parser, doc):
    assert parser(doc, OURS) == []


def test_adapter_for_resolution():
    assert adapter_for("mod") is parse_mod
    assert adapter_for("dcat2") is parse_dcat2
    assert adapter_for("ontoexplorer") is parse_mod
    assert adapter_for("generic") is parse_mod
    assert adapter_for("unknown-thing") is parse_mod
    assert adapter_for("") is parse_mod
    assert adapter_for(None) is parse_mod  # type: ignore[arg-type]
