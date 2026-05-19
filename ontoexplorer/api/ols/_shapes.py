"""Internal entity dict → OLS-shape dict transforms."""
import json
import re
from typing import Any, Literal
from fastapi import Request

# Strict-uppercase prefix per OBO Foundry URI conventions (https://obofoundry.org/principles/fp-003-uris.html)
_OBO_SHORT_RE = re.compile(r"^([A-Z]+)_(\d+)$")


def derive_obo_id(short_form: str) -> str | None:
    m = _OBO_SHORT_RE.match(short_form)
    if not m:
        return None
    return f"{m.group(1)}:{m.group(2)}"


def _filter_by_lang(items: list[dict], lang: str | None) -> list[str]:
    """Return [value, ...] filtered by lang. If lang=None: return all values.
    If lang is set: keep entries whose 'lang' matches; if none match, return all."""
    if lang is None:
        return [it["value"] for it in items]
    matches = [it["value"] for it in items if it.get("lang") == lang]
    return matches if matches else [it["value"] for it in items]


def _pick_label(items: list[dict], lang: str | None, default: str) -> str:
    if lang:
        for it in items:
            if it.get("lang") == lang:
                return it["value"]
    return default


def _parse_json_or_empty(s: str | None) -> list[dict]:
    if not s:
        return []
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return []


def _entity_self_url(
    request: Request,
    ontology_id: str,
    iri: str,
    resource_kind: str = "terms",
) -> str:
    from ontoexplorer.api.ols._iri import encode_iri_for_ols_path
    base = str(request.base_url).rstrip("/")
    return f"{base}/ols/api/ontologies/{ontology_id}/{resource_kind}/{encode_iri_for_ols_path(iri)}"


# Keep old name as an alias for backward compatibility
def _term_self_url(request: Request, ontology_id: str, iri: str) -> str:
    return _entity_self_url(request, ontology_id, iri, resource_kind="terms")


def _entity_links(
    request: Request,
    ontology_id: str,
    iri: str,
    resource_kind: str = "terms",
) -> dict[str, dict[str, str]]:
    self_url = _entity_self_url(request, ontology_id, iri, resource_kind)
    links: dict[str, dict[str, str]] = {
        "self":        {"href": self_url},
        "parents":     {"href": f"{self_url}/parents"},
        "children":    {"href": f"{self_url}/children"},
        "ancestors":   {"href": f"{self_url}/ancestors"},
        "descendants": {"href": f"{self_url}/descendants"},
    }
    if resource_kind == "terms":
        # Terms have additional hierarchical and widget links
        links["hierarchicalParents"]     = {"href": f"{self_url}/hierarchicalParents"}
        links["hierarchicalAncestors"]   = {"href": f"{self_url}/hierarchicalAncestors"}
        links["hierarchicalDescendants"] = {"href": f"{self_url}/hierarchicalDescendants"}
        links["jstree"]                  = {"href": f"{self_url}/jstree"}
        links["graph"]                   = {"href": f"{self_url}/graph"}
    return links


def _term_links(request: Request, ontology_id: str, iri: str) -> dict[str, dict[str, str]]:
    return _entity_links(request, ontology_id, iri, resource_kind="terms")


def entity_to_v1_term(
    entity: dict,
    ontology: Any,
    *,
    request: Request,
    is_obsolete: bool,
    is_root: bool,
    has_children: bool,
    lang: str | None = None,
    resource_kind: Literal["terms", "properties", "individuals"] = "terms",
) -> dict[str, Any]:
    labels = _parse_json_or_empty(entity.get("labels"))
    synonyms = _parse_json_or_empty(entity.get("synonyms"))
    definitions = _parse_json_or_empty(entity.get("definitions"))
    short = entity.get("short") or ""
    ontology_id = getattr(ontology, "shortname", None) or ontology.id
    return {
        "iri": entity["iri"],
        "label": _pick_label(labels, lang, entity.get("primary_label") or entity.get("label") or ""),
        "short_form": short,
        "obo_id": derive_obo_id(short),
        "ontology_name": ontology_id,
        "ontology_prefix": ontology_id.upper(),
        "ontology_iri": ontology.iri,
        "is_defining_ontology": (
            entity.get("source") == ontology_id
            or entity.get("source") == ontology.id  # backwards compat: pre-shortname cached entries
            or not entity.get("source")
        ),
        "description": _filter_by_lang(definitions, lang),
        "synonyms": _filter_by_lang(synonyms, lang),
        "annotation": {},
        "is_obsolete": is_obsolete,
        "term_replaced_by": None,
        "is_root": is_root,
        "has_children": has_children,
        "in_subset": [],
        "is_preferred_root": False,
        "lang": lang or "en",
        "obo_xref": [],
        "obo_definition_citation": [],
        "obo_synonym": [],
        "_links": _entity_links(request, ontology_id, entity["iri"], resource_kind),
    }


def entity_to_v2_class(entity: dict, ontology: Any, *, request: Request, lang: str | None = None) -> dict[str, Any]:
    """V2 flat shape — same field set, no _links, type-tagged."""
    v1 = entity_to_v1_term(entity, ontology,
                           request=request, is_obsolete=False, is_root=False,
                           has_children=False, lang=lang)
    v1.pop("_links", None)
    v1["type"] = ["class", "entity"]
    return v1


def _v2_type_tag(entity_type: str) -> list[str]:
    """Map internal entity type string to the OLS v2 type array."""
    if entity_type in ("object_property", "data_property", "annotation_property"):
        return ["property", "entity"]
    if entity_type == "individual":
        return ["individual", "entity"]
    # default: class
    return ["class", "entity"]


def entity_to_v2(
    entity: dict,
    ontology: Any,
    *,
    request: Request,
    lang: str | None = None,
    resource_kind: Literal["terms", "properties", "individuals"] = "terms",
) -> dict[str, Any]:
    """V2 flat shape with type derived from the entity's own ``type`` field.

    Use this for /v2/properties, /v2/individuals, and /v2/entities endpoints
    where the OLS type tag must reflect the actual entity type.
    """
    v1 = entity_to_v1_term(entity, ontology,
                           request=request, is_obsolete=False, is_root=False,
                           has_children=False, lang=lang, resource_kind=resource_kind)
    v1.pop("_links", None)
    v1["type"] = _v2_type_tag(entity.get("type", "class"))
    return v1


def ontology_to_v1(ontology: Any, version: Any, meta_counts: dict, *, request: Request) -> dict[str, Any]:
    base = str(request.base_url).rstrip("/")
    short = getattr(ontology, "shortname", None) or ontology.id
    return {
        "ontologyId": short,
        "loaded": version.created_at.isoformat() if hasattr(version.created_at, "isoformat") else str(version.created_at),
        "updated": version.created_at.isoformat() if hasattr(version.created_at, "isoformat") else str(version.created_at),
        "status": "LOADED",
        "message": "",
        "version": getattr(version, "version_iri", None) or "",
        "numberOfTerms": int(meta_counts.get("class_count", 0)),
        "numberOfProperties": int(meta_counts.get("property_count", 0)),
        "numberOfIndividuals": int(meta_counts.get("individual_count", 0)),
        "config": {
            "id": short,
            "ontologyId": short,
            "preferredPrefix": short.upper(),
            "title": getattr(ontology, "title", None) or short,
            "description": getattr(ontology, "description", None) or "",
            "homepage": "",
            "mailingList": "",
            "creators": [],
            "tracker": "",
            "logo": "",
            "license": {},
            "fileLocation": ontology.iri,
            "reasonerType": "ELK",
            "labelProperty": "http://www.w3.org/2000/01/rdf-schema#label",
            "definitionProperties": [
                "http://www.w3.org/2004/02/skos/core#definition",
                "http://purl.obolibrary.org/obo/IAO_0000115",
            ],
            "synonymProperties": [],
            "hierarchicalProperties": [],
            "baseUris": [ontology.iri],
            "hiddenProperties": [],
            "isSkosOntology": False,
            "allowDownload": True,
            "annotations": {},
        },
        "_links": {
            "self":       {"href": f"{base}/ols/api/ontologies/{short}"},
            "terms":      {"href": f"{base}/ols/api/ontologies/{short}/terms"},
            "properties": {"href": f"{base}/ols/api/ontologies/{short}/properties"},
            "individuals":{"href": f"{base}/ols/api/ontologies/{short}/individuals"},
        },
    }


def ontology_to_v2(ontology: Any, version: Any, meta_counts: dict, *, request: Request) -> dict[str, Any]:
    v1 = ontology_to_v1(ontology, version, meta_counts, request=request)
    v1.pop("_links", None)
    return v1
