from __future__ import annotations

LABEL_PROPS: list[str] = [
    "http://www.w3.org/2000/01/rdf-schema#label",
    "http://www.w3.org/2004/02/skos/core#prefLabel",
    "http://purl.org/dc/terms/title",
    "http://purl.org/dc/elements/1.1/title",
    "https://schema.org/name",
]

DEFINITION_PROPS: list[str] = [
    "http://purl.obolibrary.org/obo/IAO_0000115",
    "http://www.w3.org/2004/02/skos/core#definition",
    "http://www.w3.org/2000/01/rdf-schema#comment",
    "http://purl.org/dc/terms/description",
]

SYNONYM_PROPS: list[str] = [
    "http://www.w3.org/2004/02/skos/core#altLabel",
    "http://www.geneontology.org/formats/oboInOwl#hasExactSynonym",
    "http://www.geneontology.org/formats/oboInOwl#hasRelatedSynonym",
    "http://www.geneontology.org/formats/oboInOwl#hasBroadSynonym",
    "http://www.geneontology.org/formats/oboInOwl#hasNarrowSynonym",
]

DEPRECATED_PROPS: list[str] = [
    "http://www.w3.org/2002/07/owl#deprecated",
]

ALL_PROPS: dict[str, list[str]] = {
    "label": LABEL_PROPS,
    "definition": DEFINITION_PROPS,
    "synonym": SYNONYM_PROPS,
    "deprecated": DEPRECATED_PROPS,
}

IRI_TO_ROLE: dict[str, str] = {
    iri: role
    for role, iris in ALL_PROPS.items()
    for iri in iris
}

MOD_PREF_LABEL = "https://w3id.org/mod#prefLabelProperty"
MOD_DEFINITION = "https://w3id.org/mod#definitionProperty"


def default_profile() -> dict[str, list[str]]:
    """Return a copy of registry defaults — used when no profile row exists."""
    return {
        "label_props": LABEL_PROPS[:],
        "definition_props": DEFINITION_PROPS[:],
        "synonym_props": SYNONYM_PROPS[:],
        "deprecated_props": DEPRECATED_PROPS[:],
    }
