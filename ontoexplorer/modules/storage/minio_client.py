"""Higher-level storage module using the path conventions from the plan.

MinIO layout:
  ontologies/{ontology_id}/{version_id}/{sha256}.{ext}   -- raw ontology file
  imports/{sha256}.{ext}                                  -- cached external owl:imports
"""

from ontoexplorer.clients.minio import (
    download_bytes,
    object_exists,
    presigned_get_url,
    upload_bytes,
)
from ontoexplorer.config import get_settings


def _settings():
    return get_settings()


# ── Ontology artifacts ─────────────────────────────────────────────────────────

def ontology_key(ontology_id: str, version_id: str, sha256: str, ext: str) -> str:
    return f"{ontology_id}/{version_id}/{sha256}.{ext}"


def store_ontology(ontology_id: str, version_id: str, sha256: str, ext: str, data: bytes) -> str:
    key = ontology_key(ontology_id, version_id, sha256, ext)
    bucket = _settings().minio_ontologies_bucket
    upload_bytes(bucket, key, data, content_type=_content_type(ext))
    return key


def fetch_ontology(key: str) -> bytes:
    return download_bytes(_settings().minio_ontologies_bucket, key)


def ontology_download_url(key: str, expires_seconds: int = 3600) -> str:
    return presigned_get_url(_settings().minio_ontologies_bucket, key, expires_seconds)


# ── Import cache ───────────────────────────────────────────────────────────────

def import_key(sha256: str, ext: str) -> str:
    return f"{sha256}.{ext}"


def store_import(sha256: str, ext: str, data: bytes) -> str:
    key = import_key(sha256, ext)
    bucket = _settings().minio_imports_bucket
    upload_bytes(bucket, key, data, content_type=_content_type(ext))
    return key


def fetch_import(key: str) -> bytes:
    return download_bytes(_settings().minio_imports_bucket, key)


def import_exists(sha256: str, ext: str) -> bool:
    return object_exists(_settings().minio_imports_bucket, import_key(sha256, ext))


# ── Helpers ────────────────────────────────────────────────────────────────────

def _content_type(ext: str) -> str:
    return {
        "owl": "application/rdf+xml",
        "ttl": "text/turtle",
        "n3": "text/n3",
        "nt": "application/n-triples",
        "jsonld": "application/ld+json",
        "obo": "text/plain",
        "omn": "text/plain",
    }.get(ext.lower(), "application/octet-stream")
