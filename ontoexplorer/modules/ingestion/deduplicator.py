"""SHA-256 content-hash deduplication for ontology versions."""

import hashlib

import rdflib


def compute_sha256(graph: rdflib.Graph) -> str:
    """
    Compute a stable SHA-256 hash of an rdflib Graph.

    Serialises to sorted N-Triples (canonical form) so the hash is
    independent of parse order, blank node naming, and serialisation format.
    """
    nt_bytes = graph.serialize(format="nt").encode("utf-8")
    # Sort lines for determinism (N-Triples line order is not guaranteed)
    lines = sorted(nt_bytes.splitlines())
    canonical = b"\n".join(lines)
    return hashlib.sha256(canonical).hexdigest()


def compute_sha256_bytes(data: bytes) -> str:
    """Compute SHA-256 of raw bytes (used for import caching)."""
    return hashlib.sha256(data).hexdigest()
