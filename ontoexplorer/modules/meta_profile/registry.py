from __future__ import annotations

TITLE_PROPS: list[str] = [
    "http://purl.org/dc/terms/title",
    "http://www.w3.org/2000/01/rdf-schema#label",
    "http://purl.org/dc/elements/1.1/title",
]

SHORTNAME_PROPS: list[str] = [
    "http://purl.org/dc/terms/alternative",
    "http://www.w3.org/2002/07/owl#acronym",
]

DESCRIPTION_PROPS: list[str] = [
    "http://purl.org/dc/terms/description",
    "http://www.w3.org/2000/01/rdf-schema#comment",
    "http://purl.org/dc/elements/1.1/description",
]

CREATOR_PROPS: list[str] = [
    "http://purl.org/dc/terms/creator",
    "http://purl.org/dc/elements/1.1/creator",
    "http://purl.org/pav/authoredBy",
]

CONTRIBUTOR_PROPS: list[str] = [
    "http://purl.org/dc/terms/contributor",
]

PUBLISHER_PROPS: list[str] = [
    "http://purl.org/dc/terms/publisher",
]

LICENSE_PROPS: list[str] = [
    "http://purl.org/dc/terms/license",
    "http://purl.org/dc/terms/rights",
]

HOMEPAGE_PROPS: list[str] = [
    "http://xmlns.com/foaf/0.1/homepage",
    "http://www.w3.org/ns/dcat#accessURL",
    "https://schema.org/includedInDataCatalog",
]

VERSION_INFO_PROPS: list[str] = [
    "http://www.w3.org/2002/07/owl#versionInfo",
]

PREFIX_PROPS: list[str] = [
    "http://purl.org/vocab/vann/preferredNamespacePrefix",
]

NAMESPACE_URI_PROPS: list[str] = [
    "http://purl.org/vocab/vann/preferredNamespaceUri",
]

CREATED_PROPS: list[str] = [
    "http://purl.org/dc/terms/created",
    "http://purl.org/dc/terms/issued",
]

MODIFIED_PROPS: list[str] = [
    "http://purl.org/dc/terms/modified",
]

LANGUAGE_PROPS: list[str] = [
    "http://purl.org/dc/terms/language",
]

CITATION_PROPS: list[str] = [
    "http://purl.org/dc/terms/bibliographicCitation",
]

FUNDING_PROPS: list[str] = [
    "https://schema.org/funding",
]

STATUS_PROPS: list[str] = [
    "https://w3id.org/mod#status",
]

SYNTAX_PROPS: list[str] = [
    "https://w3id.org/mod#hasSyntax",
    "https://w3id.org/mod#hasRepresentationLanguage",
]

ALL_META_ROLES: dict[str, list[str]] = {
    "title": TITLE_PROPS,
    "shortname": SHORTNAME_PROPS,
    "description": DESCRIPTION_PROPS,
    "creator": CREATOR_PROPS,
    "contributor": CONTRIBUTOR_PROPS,
    "publisher": PUBLISHER_PROPS,
    "license": LICENSE_PROPS,
    "homepage": HOMEPAGE_PROPS,
    "version_info": VERSION_INFO_PROPS,
    "prefix": PREFIX_PROPS,
    "namespace_uri": NAMESPACE_URI_PROPS,
    "created": CREATED_PROPS,
    "modified": MODIFIED_PROPS,
    "language": LANGUAGE_PROPS,
    "citation": CITATION_PROPS,
    "funding": FUNDING_PROPS,
    "status": STATUS_PROPS,
    "syntax": SYNTAX_PROPS,
}

MULTI_VALUE_ROLES: set[str] = {"creator", "contributor", "publisher"}

ROLE_RESOLVED_KEY: dict[str, str] = {
    "title": "title",
    "shortname": "shortname",
    "description": "description",
    "creator": "creators",
    "contributor": "contributors",
    "publisher": "publishers",
    "license": "license",
    "homepage": "homepage",
    "version_info": "version_info",
    "prefix": "prefix",
    "namespace_uri": "namespace_uri",
    "created": "created",
    "modified": "modified",
    "language": "language",
    "citation": "citation",
    "funding": "funding",
    "status": "status",
    "syntax": "syntax",
}

ALL_KNOWN_IRIS: set[str] = {iri for iris in ALL_META_ROLES.values() for iri in iris}


def default_meta_profile() -> dict[str, list[str]]:
    """Return registry defaults keyed as column names (role_props)."""
    return {f"{role}_props": iris[:] for role, iris in ALL_META_ROLES.items()}
