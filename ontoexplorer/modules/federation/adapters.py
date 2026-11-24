"""Per-peer MOD-API response adapters.

Each adapter is ``(doc: dict, peer: Peer) -> list[ArtefactRow]`` and parses a
JSON-LD ``hydra:Collection`` of ``mod:SemanticArtefact`` members by plain dict
traversal (no network, no rdflib). Parsing is defensive: a malformed or empty
document yields ``[]`` and nothing here ever raises. A member needs an ``@id``
and a title; every other predicate is optional.

Predicate keys are normalised to full IRIs using the document's own
``@context`` (plus well-known prefixes), so compacted (``dcterms:title``) and
expanded (``http://purl.org/dc/terms/title``) framings parse identically.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

from ontoexplorer.modules.federation.config import Peer
from ontoexplorer.modules.federation.models import ArtefactRow, SourceRef

logger = logging.getLogger(__name__)

Adapter = Callable[[dict, Peer], list[ArtefactRow]]

_WELL_KNOWN = {
    "dcterms": "http://purl.org/dc/terms/",
    "dct": "http://purl.org/dc/terms/",
    "dcat": "http://www.w3.org/ns/dcat#",
    "mod": "https://w3id.org/mod#",
    "foaf": "http://xmlns.com/foaf/0.1/",
    "void": "http://rdfs.org/ns/void#",
    "hydra": "http://www.w3.org/ns/hydra/core#",
    "owl": "http://www.w3.org/2002/07/owl#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "schema": "https://schema.org/",
}

_DCT = _WELL_KNOWN["dcterms"]
_DCAT = _WELL_KNOWN["dcat"]
_MOD = _WELL_KNOWN["mod"]
_FOAF = _WELL_KNOWN["foaf"]
_HYDRA = _WELL_KNOWN["hydra"]
_RDFS = _WELL_KNOWN["rdfs"]
_SKOS = _WELL_KNOWN["skos"]

_TITLE = (_DCT + "title", _RDFS + "label", _SKOS + "prefLabel")
_DESCRIPTION = (_DCT + "description",)
_ACRONYM = (_MOD + "acronym",)
_IDENTIFIER = (_DCT + "identifier",)
_PUBLISHER = (_DCT + "publisher",)
_LICENSE = (_DCT + "license",)
_HOMEPAGE = (_FOAF + "homepage", _DCAT + "landingPage")
_NAME = (_FOAF + "name", _DCT + "title", _RDFS + "label", _WELL_KNOWN["schema"] + "name")

# Predicates under which a collection document lists its artefacts.
_MEMBER_KEYS = (_HYDRA + "member", _DCAT + "dataset", _DCAT + "Resource", _DCAT + "resource")
_COLLECTION_TYPES = {_HYDRA + "Collection", _HYDRA + "PartialCollectionView"}


# ---------------------------------------------------------------- helpers


def _context_map(doc: Any) -> dict[str, str]:
    """prefix/term -> IRI from the doc's @context (dict or list of dicts)."""
    out: dict[str, str] = {}
    ctx = doc.get("@context") if isinstance(doc, dict) else None
    for part in ctx if isinstance(ctx, list) else [ctx]:
        if not isinstance(part, dict):
            continue
        for k, v in part.items():
            if k.startswith("@"):
                continue
            if isinstance(v, str):
                out[k] = v
            elif isinstance(v, dict) and isinstance(v.get("@id"), str):
                out[k] = v["@id"]
    return out


def _expand(key: str, ctx: dict[str, str]) -> str:
    if key.startswith("@"):
        return key
    if key in ctx:
        target = ctx[key]
        # a term may map to a compact IRI ("title": "dcterms:title"); expand once
        return _expand(target, {}) if target != key else target
    prefix, sep, rest = key.partition(":")
    if sep and not rest.startswith("//"):
        base = ctx.get(prefix) or _WELL_KNOWN.get(prefix)
        if base:
            return base + rest
    return key


def _normalise(node: dict, ctx: dict[str, str]) -> dict[str, Any]:
    return {_expand(k, ctx): v for k, v in node.items() if isinstance(k, str)}


def _as_list(v: Any) -> list:
    if v is None:
        return []
    if isinstance(v, dict) and "@list" in v:
        return _as_list(v["@list"])
    return v if isinstance(v, list) else [v]


def _is_english(v: Any) -> bool:
    return isinstance(v, dict) and str(v.get("@language", "")).lower().startswith("en")


def _scalar(v: Any, ctx: dict[str, str]) -> str | None:
    """Best string for one JSON-LD value: literal, IRI reference, or named node."""
    if isinstance(v, str):
        return v.strip() or None
    if isinstance(v, dict):
        lit = v.get("@value")
        if isinstance(lit, str):
            return lit.strip() or None
        node = _normalise(v, ctx)
        for name_key in _NAME:
            for cand in _as_list(node.get(name_key)):
                s = _scalar(cand, ctx) if not isinstance(cand, dict) or "@value" in cand else None
                if s:
                    return s
        iri = v.get("@id")
        if isinstance(iri, str):
            return iri.strip() or None
    return None


def _first(node: dict[str, Any], keys: tuple[str, ...], ctx: dict[str, str]) -> str | None:
    for key in keys:
        vals = _as_list(node.get(key))
        # prefer an English literal, else the first value that yields text
        for v in vals:
            if _is_english(v):
                s = _scalar(v, ctx)
                if s:
                    return s
        for v in vals:
            s = _scalar(v, ctx)
            if s:
                return s
    return None


def _iri_tail(iri: str) -> str:
    tail = iri.rstrip("/#").rsplit("#", 1)[-1].rsplit("/", 1)[-1]
    return tail or iri


def _types(node: dict[str, Any], ctx: dict[str, str]) -> set[str]:
    return {_expand(t, ctx) for t in _as_list(node.get("@type")) if isinstance(t, str)}


def _row(raw: Any, ctx: dict[str, str], peer: Peer) -> ArtefactRow | None:
    if not isinstance(raw, dict):
        return None
    iri = raw.get("@id")
    if not isinstance(iri, str) or not iri.strip():
        return None
    node = _normalise(raw, ctx)
    if _types(node, ctx) & _COLLECTION_TYPES:
        return None
    title = _first(node, _TITLE, ctx)
    if not title:
        return None
    iri = iri.strip()
    acronym = _first(node, _ACRONYM, ctx) or _first(node, _IDENTIFIER, ctx) or _iri_tail(iri)
    homepage = _first(node, _HOMEPAGE, ctx)
    landing = homepage or f"{peer.base_url.rstrip('/')}/mod/artefacts/{quote(acronym, safe='')}"
    return ArtefactRow(
        iri=iri,
        acronym=acronym,
        title=title,
        description=_first(node, _DESCRIPTION, ctx) or "",
        publisher=_first(node, _PUBLISHER, ctx),
        license=_first(node, _LICENSE, ctx),
        homepage=homepage,
        source_landing_url=landing,
        source=SourceRef(id=peer.id, label=peer.label),
    )


def _members(doc: Any, ctx: dict[str, str]) -> list[Any]:
    if isinstance(doc, list):
        return doc
    if not isinstance(doc, dict):
        return []
    # A bare "member" key is hydra's JSON-LD term for hydra:member.
    node = _normalise({("hydra:member" if k == "member" else k): v for k, v in doc.items()}, ctx)
    found: list[Any] = []
    for key in _MEMBER_KEYS:
        found.extend(_as_list(node.get(key)))
    if found:
        return found
    graph = node.get("@graph")
    if isinstance(graph, list):
        return graph
    return []


def _parse(doc: Any, peer: Peer) -> list[ArtefactRow]:
    try:
        ctx = _context_map(doc)
        rows: list[ArtefactRow] = []
        for raw in _members(doc, ctx):
            try:
                row = _row(raw, ctx, peer)
            except Exception:  # one bad member must not drop the rest
                logger.debug("federation: skipping malformed member from %s", peer.id, exc_info=True)
                continue
            if row is not None:
                rows.append(row)
        return rows
    except Exception:
        logger.warning("federation: could not parse response from peer %s", peer.id, exc_info=True)
        return []


# --------------------------------------------------------------- adapters


def parse_mod(doc: dict, peer: Peer) -> list[ArtefactRow]:
    """Default parser: MOD/DCTERMS/FOAF predicates on ``mod:SemanticArtefact`` members.

    Also used for OntoExplorer peers (same vocabulary as our own server).
    """
    return _parse(doc, peer)


def parse_dcat2(doc: dict, peer: Peer) -> list[ArtefactRow]:
    """AgroPortal-style variant: same core predicates, DCAT2-leaning framing.

    Members may sit under ``dcat:dataset`` / ``dcat:Resource`` as well as
    ``hydra:member``, and the landing page may be ``dcat:landingPage``.
    """
    return _parse(doc, peer)


parse_ontoexplorer = parse_mod
parse_generic = parse_mod

_ADAPTERS: dict[str, Adapter] = {
    "mod": parse_mod,
    "ontoexplorer": parse_mod,
    "generic": parse_mod,
    "dcat2": parse_dcat2,
}


def adapter_for(name: str | None) -> Adapter:
    """Resolve ``Peer.adapter`` to a parser; unknown names get the default ``mod``."""
    return _ADAPTERS.get((name or "").strip().lower(), parse_mod)
