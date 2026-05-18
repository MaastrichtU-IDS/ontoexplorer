"""Internal entity dict → OLS-shape dict transforms."""
import json
import re
from typing import Any
from fastapi import Request

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


def _term_self_url(request: Request, ontology_id: str, iri: str) -> str:
    from ontoexplorer.api.ols._iri import encode_iri_for_ols_path
    base = str(request.url).split("/ols/api")[0]
    return f"{base}/ols/api/ontologies/{ontology_id}/terms/{encode_iri_for_ols_path(iri)}"


def _term_links(request: Request, ontology_id: str, iri: str) -> dict[str, dict[str, str]]:
    self_url = _term_self_url(request, ontology_id, iri)
    return {
        "self":                       {"href": self_url},
        "parents":                    {"href": f"{self_url}/parents"},
        "children":                   {"href": f"{self_url}/children"},
        "ancestors":                  {"href": f"{self_url}/ancestors"},
        "descendants":                {"href": f"{self_url}/descendants"},
        "hierarchicalParents":        {"href": f"{self_url}/hierarchicalParents"},
        "hierarchicalAncestors":      {"href": f"{self_url}/hierarchicalAncestors"},
        "hierarchicalDescendants":    {"href": f"{self_url}/hierarchicalDescendants"},
        "jstree":                     {"href": f"{self_url}/jstree"},
        "graph":                      {"href": f"{self_url}/graph"},
    }


def entity_to_v1_term(
    entity: dict,
    ontology: Any,
    *,
    version_id: str,
    request: Request,
    is_obsolete: bool,
    is_root: bool,
    has_children: bool,
    lang: str | None = None,
) -> dict[str, Any]:
    labels = _parse_json_or_empty(entity.get("labels"))
    synonyms = _parse_json_or_empty(entity.get("synonyms"))
    definitions = _parse_json_or_empty(entity.get("definitions"))
    short = entity.get("short") or ""
    ontology_id = ontology.id
    return {
        "iri": entity["iri"],
        "label": _pick_label(labels, lang, entity.get("primary_label") or entity.get("label") or ""),
        "short_form": short,
        "obo_id": derive_obo_id(short),
        "ontology_name": ontology_id,
        "ontology_prefix": ontology_id.upper(),
        "ontology_iri": ontology.iri,
        "is_defining_ontology": entity.get("source") == ontology_id or not entity.get("source"),
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
        "_links": _term_links(request, ontology_id, entity["iri"]),
    }


def entity_to_v2_class(entity: dict, ontology: Any, *, request: Request, lang: str | None = None) -> dict[str, Any]:
    """V2 flat shape — same field set, no _links, type-tagged."""
    v1 = entity_to_v1_term(entity, ontology, version_id="",
                           request=request, is_obsolete=False, is_root=False,
                           has_children=False, lang=lang)
    v1.pop("_links", None)
    v1["type"] = ["class", "entity"]
    return v1


def ontology_to_v1(ontology: Any, version: Any, meta_counts: dict, *, request: Request) -> dict[str, Any]:
    base = str(request.url).split("/ols/api")[0]
    return {
        "ontologyId": ontology.id,
        "loaded": version.created_at.isoformat() if hasattr(version.created_at, "isoformat") else str(version.created_at),
        "updated": version.created_at.isoformat() if hasattr(version.created_at, "isoformat") else str(version.created_at),
        "status": "LOADED",
        "message": "",
        "version": getattr(version, "version_iri", None) or "",
        "numberOfTerms": int(meta_counts.get("class_count", 0)),
        "numberOfProperties": int(meta_counts.get("property_count", 0)),
        "numberOfIndividuals": int(meta_counts.get("individual_count", 0)),
        "config": {
            "id": ontology.id,
            "ontologyId": ontology.id,
            "preferredPrefix": ontology.id.upper(),
            "title": getattr(ontology, "title", None) or ontology.id,
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
            "self":       {"href": f"{base}/ols/api/ontologies/{ontology.id}"},
            "terms":      {"href": f"{base}/ols/api/ontologies/{ontology.id}/terms"},
            "properties": {"href": f"{base}/ols/api/ontologies/{ontology.id}/properties"},
            "individuals":{"href": f"{base}/ols/api/ontologies/{ontology.id}/individuals"},
        },
    }


def ontology_to_v2(ontology: Any, version: Any, meta_counts: dict, *, request: Request) -> dict[str, Any]:
    v1 = ontology_to_v1(ontology, version, meta_counts, request=request)
    v1.pop("_links", None)
    return v1
