"""Materialize a single N-Triples file per reasoning scope.

For each scope we extract the relevant subset of the OntoExplorer pyoxigraph
store + optionally append fetched MIREOT-source bytes, and write to disk so
Konclude / ROBOT can read it.
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Iterable

import pyoxigraph

from ontoexplorer.clients.oxigraph import get_store


_VALID_SCOPES = {
    "host_only",
    "host_plus_imports",
    "host_plus_imports_plus_mireot",
}


def build_merge(
    *,
    out_dir: Path,
    host_graph_iri: str,
    import_graph_iris: list[str],
    mireot_source_paths: list[Path],
    scope: str,
) -> Path:
    """Build a single .nt file representing the merged ontology for the given scope.

    Returns the path to the written file.
    """
    if scope not in _VALID_SCOPES:
        raise ValueError(f"unknown scope: {scope!r} (must be one of {_VALID_SCOPES})")

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"merge_{scope}.nt"

    graphs_to_dump = [host_graph_iri]
    if scope in ("host_plus_imports", "host_plus_imports_plus_mireot"):
        graphs_to_dump.extend(import_graph_iris)

    store = get_store()
    with out_path.open("wb") as out_f:
        for g_iri in graphs_to_dump:
            _dump_graph_as_nt(store, g_iri, out_f)
        if scope == "host_plus_imports_plus_mireot":
            for src_path in mireot_source_paths:
                # Append the MIREOT source bytes verbatim — they're already N-Triples
                # (the resolver converts whatever format the source ships in to N-Triples).
                src_bytes = src_path.read_bytes()
                out_f.write(src_bytes)
                if not src_bytes.endswith(b"\n"):
                    out_f.write(b"\n")

    return out_path


def _dump_graph_as_nt(store: pyoxigraph.Store, graph_iri: str, out: io.BufferedWriter) -> None:
    """Serialize all quads in `graph_iri` as N-Triples (dropping the graph component)."""
    g = pyoxigraph.NamedNode(graph_iri)
    for quad in store.quads_for_pattern(None, None, None, g):
        triple = pyoxigraph.Triple(quad.subject, quad.predicate, quad.object)
        out.write(_serialize_triple_nt(triple).encode())
        out.write(b"\n")


def _serialize_triple_nt(triple: pyoxigraph.Triple) -> str:
    """Render a single triple as N-Triples line (no trailing newline)."""
    return f"{_term_nt(triple.subject)} {_term_nt(triple.predicate)} {_term_nt(triple.object)} ."


def _term_nt(term) -> str:
    """N-Triples serialization of a single term."""
    if isinstance(term, pyoxigraph.NamedNode):
        return f"<{term.value}>"
    if isinstance(term, pyoxigraph.BlankNode):
        return f"_:{term.value}"
    if isinstance(term, pyoxigraph.Literal):
        # Best-effort literal serialization. pyoxigraph's Literal has .value, .language, .datatype
        escaped = term.value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r")
        s = f'"{escaped}"'
        if term.language:
            s += f"@{term.language}"
        elif term.datatype is not None and term.datatype.value != "http://www.w3.org/2001/XMLSchema#string":
            s += f"^^<{term.datatype.value}>"
        return s
    raise TypeError(f"Unsupported term type: {type(term)}")
