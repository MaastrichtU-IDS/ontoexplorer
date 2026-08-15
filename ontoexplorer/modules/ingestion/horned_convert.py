"""Convert OWL serializations that the RDF stack can't parse — Manchester
(`.omn`), OBO flat-file (`.obo`), and OWL Functional (`.ofn`) — into Turtle, by
shelling out to the `horned-convert` binary (horned-owl's CLI). The Turtle then
streams into Oxigraph via the normal bulk-load fast path, so these uploads are
ingested without rdflib/pyoxigraph support for them (they have none) and no
py-horned-owl binding changes.

Turtle (not N-Triples) because horned-owl can emit a *relative* IRI for an OBO
ontology node (e.g. `ontology: my-onto` -> `<my-onto>` when it isn't a
PURL-expandable id). N-Triples requires absolute IRIs and pyoxigraph rejects the
relative one; Turtle resolves it against the loader's base_iri instead.

The binary is built into the image (see the root Dockerfile's horned-build
stage). `horned-convert` auto-detects the input format, so we hand it a temp
file with the right extension and read Turtle off stdout.
"""
from __future__ import annotations

import os
import subprocess
import tempfile

from ontoexplorer.modules.ingestion.format_detect import OntologyFormat

# Formats we route through horned-convert instead of rdflib/pyoxigraph. OBO is
# convertible by rdflib too (via plugin) but horned-owl's reader is higher
# fidelity (canonical OBO PURLs + oboInOwl annotations); Manchester has no other
# parser in the stack at all.
CONVERTIBLE: frozenset[OntologyFormat] = frozenset(
    {OntologyFormat.MANCHESTER, OntologyFormat.OBO, OntologyFormat.OWL_FUNCTIONAL}
)

# File extension handed to horned-convert so its content/extension sniffing picks
# the right reader.
_EXT: dict[OntologyFormat, str] = {
    OntologyFormat.MANCHESTER: ".omn",
    OntologyFormat.OBO: ".obo",
    OntologyFormat.OWL_FUNCTIONAL: ".ofn",
}

_BIN = os.getenv("HORNED_CONVERT_BIN", "horned-convert")
_TIMEOUT_S = int(os.getenv("HORNED_CONVERT_TIMEOUT_S", "300"))


class HornedConvertError(RuntimeError):
    """horned-convert failed (missing binary, unparseable input, timeout)."""


def to_turtle(data: bytes, fmt: OntologyFormat) -> bytes:
    """Convert `data` (in `fmt`) to Turtle bytes via horned-convert.

    Turtle rather than N-Triples so relative IRIs (which horned-owl can emit for
    an OBO ontology node) resolve against the loader's base_iri instead of being
    rejected. Raises HornedConvertError on any failure (missing binary, parse
    error, timeout, non-zero exit). Callers decide whether to fall back or surface it.
    """
    if fmt not in _EXT:
        raise HornedConvertError(f"{fmt.value} is not a horned-convert format")

    with tempfile.NamedTemporaryFile(suffix=_EXT[fmt]) as tmp:
        tmp.write(data)
        tmp.flush()
        try:
            proc = subprocess.run(
                [_BIN, tmp.name, "--to", "ttl"],
                capture_output=True,
                timeout=_TIMEOUT_S,
            )
        except FileNotFoundError as exc:
            raise HornedConvertError(f"{_BIN} not found on PATH") from exc
        except subprocess.TimeoutExpired as exc:
            raise HornedConvertError(
                f"horned-convert timed out after {_TIMEOUT_S}s"
            ) from exc

    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", "replace").strip()[:500]
        raise HornedConvertError(
            f"horned-convert exited {proc.returncode}: {stderr or 'no stderr'}"
        )
    if not proc.stdout.strip():
        raise HornedConvertError("horned-convert produced no output")
    return proc.stdout
