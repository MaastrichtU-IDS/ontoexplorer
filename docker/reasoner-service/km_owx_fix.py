"""Prepare the OWL/XML fed to km so km reads exactly the logical content.

Three km input problems, all fixed losslessly on the OWL/XML that horned-owl
produces (after the disjointness fix), before ``km classify`` sees it:

1. **IRIs mangled against the ontology IRI (silent in km v1.3.0).** km shortens
   any IRI that starts with the ontology IRI. For Pizza (ontology IRI
   ``http://www.co-ode.org/ontologies/pizza``, classes
   ``.../pizza/pizza.owl#X``) km v1.3.0 returned every inferred subsumption with
   IRIs like ``/pizza.owl#American``; km v1.5.3 instead fails to re-parse its own
   output (``Ontology( /2.0.0``). Fix: drop ``ontologyIRI``, ``versionIRI`` and
   ``xml:base`` from the root element. They name the document and carry no
   logical meaning; horned-owl already writes every IRI in full.

2. **Annotations rejected by km's strict input checks (km >= v1.4.4).** km now
   refuses annotation content that is common in published ontologies: an
   ontology annotation using the reserved ``owl:versionIRI`` property (which
   horned-owl emits), or literals typed with non-OWL-2 datatypes such as
   ``xsd:date`` (ubiquitous in OBO metadata). Fix: remove all annotations
   (ontology header annotations, annotation assertions, annotation property
   axioms, and annotations nested in axioms). Annotations have no logical
   meaning in OWL 2, so classification and consistency are unchanged.

3. **Undeclared entities rejected (km >= v1.4.4).** km refuses any entity used
   without a matching declaration, and horned-owl emits no declarations for
   undeclared entities (very common, e.g. classes that appear only in axioms).
   Fix: add a ``<Declaration>`` for every (kind, IRI) that is used but not
   declared. Declarations carry no logical meaning either.

Scope of (3) mirrors km's own check: individuals are not declared (km does not
require it); built-in owl:/rdf:/rdfs:/xsd: IRIs are implicitly declared; an IRI
used with incompatible kinds (e.g. ObjectProperty and DataProperty) gets both
declarations so km reports the genuine "incompatible entity types" error, which
is a real OWL 2 DL violation this module deliberately does not paper over.
"""
from __future__ import annotations

_OWL = "http://www.w3.org/2002/07/owl#"
_RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
_RDFS = "http://www.w3.org/2000/01/rdf-schema#"
_XSD = "http://www.w3.org/2001/XMLSchema#"
_XML_BASE = "{http://www.w3.org/XML/1998/namespace}base"

_BUILTIN_NS = (_OWL, _RDF, _RDFS, _XSD)

# OWL/XML entity element names km requires a declaration for (NamedIndividual
# is deliberately absent, matching km).
_KINDS = ("Class", "ObjectProperty", "DataProperty", "AnnotationProperty", "Datatype")

# Elements that carry only annotation (non-logical) content.
_ANNOTATION_ELEMENTS = (
    "Annotation", "AnnotationAssertion", "SubAnnotationPropertyOf",
    "AnnotationPropertyDomain", "AnnotationPropertyRange",
)

_HEADER_ATTRS = ("ontologyIRI", "versionIRI", _XML_BASE)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _resolve(elem, prefixes: dict[str, str]) -> str | None:
    iri = elem.get("IRI")
    if iri is not None:
        return iri
    abbrev = elem.get("abbreviatedIRI")
    if abbrev is not None and ":" in abbrev:
        pfx, local = abbrev.split(":", 1)
        if pfx in prefixes:
            return prefixes[pfx] + local
    return None


def _prefixes(root) -> dict[str, str]:
    return {p.get("name", ""): p.get("IRI", "") for p in root if _local(p.tag) == "Prefix"}


def strip_header_and_annotations(root) -> int:
    """Remove the root's naming attributes and every annotation element, in place.
    Returns the number of annotation elements removed."""
    for attr in _HEADER_ATTRS:
        root.attrib.pop(attr, None)
    removed = 0

    def prune(elem) -> None:
        nonlocal removed
        for child in list(elem):
            if _local(child.tag) in _ANNOTATION_ELEMENTS:
                elem.remove(child)
                removed += 1
            else:
                prune(child)

    prune(root)
    return removed


def undeclared_entities(root) -> list[tuple[str, str]]:
    """Sorted ``(kind, iri)`` pairs used under ``root`` without a matching declaration."""
    prefixes = _prefixes(root)
    declared: set[tuple[str, str]] = set()
    used: set[tuple[str, str]] = set()

    def walk(elem, in_declaration: bool) -> None:
        name = _local(elem.tag)
        if name in _KINDS:
            iri = _resolve(elem, prefixes)
            if iri is not None and not iri.startswith(_BUILTIN_NS):
                (declared if in_declaration else used).add((name, iri))
        inside = in_declaration or name == "Declaration"
        for child in elem:
            walk(child, inside)

    walk(root, False)
    return sorted(used - declared)


def prepare_owx_for_km(owx: str) -> tuple[str, list[tuple[str, str]]]:
    """Return ``(owx_for_km, injected_declarations)``.

    Applies (1)-(3) from the module docstring. If ``owx`` is not well-formed XML
    it is returned untouched (with nothing injected) so km reports the real
    problem. Safe to call unconditionally.
    """
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(owx)
    except ET.ParseError:
        return owx, []
    if _local(root.tag) != "Ontology":
        return owx, []

    strip_header_and_annotations(root)
    missing = undeclared_entities(root)
    if missing:
        ns = root.tag[: root.tag.index("}") + 1] if root.tag.startswith("{") else ""
        for kind, iri in missing:
            decl = ET.SubElement(root, ns + "Declaration")
            ET.SubElement(decl, ns + kind, {"IRI": iri})

    if root.tag.startswith("{"):
        ET.register_namespace("", root.tag[1: root.tag.index("}")])
    return ET.tostring(root, encoding="unicode"), missing
