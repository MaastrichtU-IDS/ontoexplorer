"""Redis-backed classification result cache."""
from __future__ import annotations

import gzip
import json
import os
from dataclasses import asdict

import redis

from classifier import ClassificationResult

_CLASSIFICATION_TTL = int(os.getenv("CLASSIFICATION_TTL_SECONDS", str(30 * 24 * 3600)))
_JUSTIFICATION_TTL  = int(os.getenv("JUSTIFICATION_TTL_SECONDS",  str(7  * 24 * 3600)))
_REDIS_URL          = os.getenv("REDIS_URL", "redis://localhost:6379/2")

_redis: redis.Redis = redis.from_url(_REDIS_URL, decode_responses=False)


def _classification_key(version_id: str, reasoner: str) -> str:
    return f"classification:{version_id}:{reasoner}"


def _input_axioms_key(version_id: str, reasoner: str) -> str:
    return f"input_axioms:{version_id}:{reasoner}"


def _classification_error_key(version_id: str, reasoner: str) -> str:
    return f"classification_error:{version_id}:{reasoner}"


def _justification_key(version_id: str, sub: str, sup: str | None, max_j: int, reasoner: str) -> str:
    import hashlib
    raw = f"{sub}|{sup}|{max_j}"
    h = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return f"justification:{version_id}:{reasoner}:{h}"


def _ofn_key(version_id: str) -> str:
    # The OWL-functional serialization is reasoner-independent (it's just the
    # ontology), so it is NOT keyed by reasoner — one .ofn per version.
    return f"ofn:{version_id}"


# The four per-class maps, stored one Redis hash each so a single class can be
# read without materialising the whole classification.
_PER_CLASS_MAPS = ("superclasses", "subclasses", "direct_superclasses", "direct_subclasses")


def _per_class_key(version_id: str, reasoner: str, which: str) -> str:
    return f"classification:{version_id}:{reasoner}:{which}"


def _per_class_index_key(version_id: str, reasoner: str) -> str:
    """Every class named anywhere in the classification, for membership checks."""
    return f"classification:{version_id}:{reasoner}:classes"


def store_classification(result: ClassificationResult, reasoner: str) -> None:
    key = _classification_key(result.version_id, reasoner)
    data = json.dumps(asdict(result)).encode()
    _redis.setex(key, _CLASSIFICATION_TTL, gzip.compress(data))
    store_per_class(result, reasoner)
    clear_classification_error(result.version_id, reasoner)


def store_per_class(result: ClassificationResult, reasoner: str) -> None:
    """Write each map as a hash of class IRI -> JSON list.

    The blob above is still the source of truth for whole-ontology questions.
    This exists so that answering "what are C's subclasses?" costs one HGET
    rather than decompressing and parsing the entire result — 8.5 s and ~539 MB
    on DRON, per request, which was killing the service's workers.
    """
    version_id = result.version_id
    as_dict = asdict(result)
    known: set[str] = set()

    pipe = _redis.pipeline()
    for which in _PER_CLASS_MAPS:
        mapping = as_dict.get(which) or {}
        key = _per_class_key(version_id, reasoner, which)
        pipe.delete(key)          # a re-run must not leave stale classes behind
        if mapping:
            pipe.hset(key, mapping={k: json.dumps(v) for k, v in mapping.items()})
            pipe.expire(key, _CLASSIFICATION_TTL)
        known.update(mapping.keys())

    index_key = _per_class_index_key(version_id, reasoner)
    pipe.delete(index_key)
    if known:
        pipe.sadd(index_key, *known)
        pipe.expire(index_key, _CLASSIFICATION_TTL)
    pipe.execute()


def load_class_entry(
    version_id: str, reasoner: str, which: str, cls: str
) -> list[str] | None:
    """One class's entry from one map, or None when it has no entry.

    None and [] are different answers: [] means the classification knows this
    class and it has nothing in this direction, None means no entry at all.
    """
    raw = _redis.hget(_per_class_key(version_id, reasoner, which), cls)
    return json.loads(raw) if raw is not None else None


def has_per_class_index(version_id: str, reasoner: str) -> bool:
    """Whether per-class entries exist for this version.

    Classifications produced before this was added only have the blob, so
    callers check here and fall back rather than reporting a class as unknown.
    """
    return bool(_redis.exists(_per_class_index_key(version_id, reasoner)))


def class_is_known(version_id: str, reasoner: str, cls: str) -> bool:
    """Whether the classification mentions this class at all (for 404s)."""
    return bool(_redis.sismember(_per_class_index_key(version_id, reasoner), cls))


def load_classification(version_id: str, reasoner: str) -> ClassificationResult | None:
    raw = _redis.get(_classification_key(version_id, reasoner))
    if raw is None:
        return None
    return ClassificationResult(**json.loads(gzip.decompress(raw)))


def store_justification(version_id: str, sub: str, sup: str | None, max_j: int, reasoner: str, result: dict) -> None:
    _redis.setex(_justification_key(version_id, sub, sup, max_j, reasoner),
                 _JUSTIFICATION_TTL, json.dumps(result).encode())


def load_justification(version_id: str, sub: str, sup: str | None, max_j: int, reasoner: str) -> dict | None:
    raw = _redis.get(_justification_key(version_id, sub, sup, max_j, reasoner))
    return json.loads(raw) if raw else None


def store_input_axioms(version_id: str, ntriples: str, reasoner: str) -> None:
    """Persist raw input N-Triples so justification works uniformly across backends (whelk emits no proof traces).
    Uses same TTL as classification to keep them in lockstep."""
    _redis.setex(_input_axioms_key(version_id, reasoner),
                 _CLASSIFICATION_TTL, gzip.compress(ntriples.encode("utf-8")))


def load_input_axioms(version_id: str, reasoner: str) -> str | None:
    raw = _redis.get(_input_axioms_key(version_id, reasoner))
    return gzip.decompress(raw).decode("utf-8") if raw is not None else None


def store_ontology_ofn(version_id: str, ofn: str) -> None:
    """Cache the OWL-functional (.ofn) serialization of a version's ontology.

    rustdl's justify re-parses and re-classifies the ontology on every call
    (no reuse API), and .ofn (OWL functional) is ~2.5x smaller than the RDF/XML
    we'd otherwise materialise and parses substantially faster in rustdl — so we
    build it once (lazily, on first justify) and reuse it for every subsequent
    justify of the same version. Same TTL as classification/input axioms."""
    _redis.setex(_ofn_key(version_id), _CLASSIFICATION_TTL,
                 gzip.compress(ofn.encode("utf-8")))


def load_ontology_ofn(version_id: str) -> str | None:
    raw = _redis.get(_ofn_key(version_id))
    return gzip.decompress(raw).decode("utf-8") if raw is not None else None


def store_classification_error(version_id: str, message: str, reasoner: str) -> None:
    """Surface a failed classification as a 500 via the GET endpoint instead of a permanent 409."""
    _redis.setex(_classification_error_key(version_id, reasoner),
                 _CLASSIFICATION_TTL, message.encode("utf-8"))


def load_classification_error(version_id: str, reasoner: str) -> str | None:
    raw = _redis.get(_classification_error_key(version_id, reasoner))
    return raw.decode("utf-8") if raw else None


def clear_classification_error(version_id: str, reasoner: str) -> None:
    _redis.delete(_classification_error_key(version_id, reasoner))


def invalidate_version(version_id: str) -> None:
    """Remove ALL cache entries for a version across every reasoner variant. Called on version deprecation."""
    keys = set()
    for pat in (f"classification:{version_id}:*", f"input_axioms:{version_id}:*",
                f"classification_error:{version_id}:*", f"justification:{version_id}:*",
                f"ofn:{version_id}"):
        keys.update(_redis.scan_iter(pat))
    if keys:
        _redis.delete(*keys)
