"""Work around horned-owl's RDF reader aborting on a multi-typed ontology node.

The reasoner (rustdl, PyO3/horned-owl) classifies via horned-owl's strict RDF/XML
reader. That reader ABORTS the whole parse when the ontology node — the subject of
``rdf:type owl:Ontology`` — carries any *additional* ``rdf:type`` beyond
``owl:Ontology``. This is extremely common registry/catalogue metadata: LOV stamps
``<ont> a voaf:Vocabulary``, ADMS/DCAT exports add ``adms:SemanticAsset`` /
``dcat:Dataset``, etc. horned-owl reports e.g.::

    Validity Error: Invalid annotation found [Iri(ont), RDF(Type), Iri(voaf:Vocabulary)]

and the classify subprocess exits with a ParseError — even though the ontology is
otherwise valid and small. These ontologies INDEX fine (the indexer is lenient);
only the strict reasoner path chokes. This is the single largest bucket of the
reasoned-coverage gap.

Fix: before serializing the store to RDF/XML for the reasoner, drop the *other*
``rdf:type`` triples on any ``owl:Ontology`` subject, keeping ``owl:Ontology``
itself. Those types are ontology-level metadata and irrelevant to classification,
so removing them is lossless for the reasoner's purpose and restores the parse.

The proper long-term fix is upstream in horned-owl's RDF reader (treat an extra
type on the ontology node as an ignorable annotation rather than a fatal error);
this keeps the service classifying in the meantime.
"""
from __future__ import annotations

_OWL = "http://www.w3.org/2002/07/owl#"
_RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"


def strip_extra_ontology_types(store) -> int:
    """Remove every ``rdf:type`` triple on an ``owl:Ontology`` subject whose object
    is not ``owl:Ontology``. Mutates ``store`` in place; returns the number of
    triples removed (0 if there is nothing to fix). Safe to call unconditionally —
    it scans only subjects already typed ``owl:Ontology``.
    """
    import pyoxigraph

    rdf_type = pyoxigraph.NamedNode(_RDF + "type")
    owl_ontology = pyoxigraph.NamedNode(_OWL + "Ontology")

    ontology_subjects = [
        q.subject
        for q in store.quads_for_pattern(None, rdf_type, owl_ontology, None)
    ]

    removed = 0
    for subj in ontology_subjects:
        for q in list(store.quads_for_pattern(subj, rdf_type, None, None)):
            obj = q.object
            if isinstance(obj, pyoxigraph.NamedNode) and obj.value == _OWL + "Ontology":
                continue
            store.remove(q)
            removed += 1
    return removed
