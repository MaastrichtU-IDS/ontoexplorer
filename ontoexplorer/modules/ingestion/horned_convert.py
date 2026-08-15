"""Convert OWL serializations that the RDF stack can't parse — Manchester
(`.omn`) and OBO flat-file (`.obo`) — into N-Triples, by shelling out to the
`horned-convert` binary (horned-owl's CLI). The N-Triples then stream into
Oxigraph via the normal bulk-load fast path, so Manchester/OBO uploads are
ingested with no rdflib/pyoxigraph Manchester support (they have none) and no
py-horned-owl binding changes.

The binary is built into the image (see the root Dockerfile's horned-build
stage). `horned-convert` auto-detects the input format, so we hand it a temp
file with the right extension and read N-Triples off stdout.
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
    {OntologyFormat.MANCHESTER, OntologyFormat.OBO}
)

# File extension handed to horned-convert so its content/extension sniffing picks
# the right reader.
_EXT: dict[OntologyFormat, str] = {
    OntologyFormat.MANCHESTER: ".omn",
    OntologyFormat.OBO: ".obo",
}

_BIN = os.getenv("HORNED_CONVERT_BIN", "horned-convert")
_TIMEOUT_S = int(os.getenv("HORNED_CONVERT_TIMEOUT_S", "300"))


class HornedConvertError(RuntimeError):
    """horned-convert failed (missing binary, unparseable input, timeout)."""


def to_ntriples(data: bytes, fmt: OntologyFormat) -> bytes:
    """Convert `data` (in `fmt`) to N-Triples bytes via horned-convert.

    Raises HornedConvertError on any failure (missing binary, parse error,
    timeout, non-zero exit). Callers decide whether to fall back or surface it.
    """
    if fmt not in _EXT:
        raise HornedConvertError(f"{fmt.value} is not a horned-convert format")

    with tempfile.NamedTemporaryFile(suffix=_EXT[fmt]) as tmp:
        tmp.write(data)
        tmp.flush()
        try:
            proc = subprocess.run(
                [_BIN, tmp.name, "--to", "nt"],
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
