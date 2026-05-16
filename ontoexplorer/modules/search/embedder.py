from __future__ import annotations

import hashlib
import json
import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastembed import TextEmbedding

_MODEL_NAME = "nomic-ai/nomic-embed-text-v1.5"
_embedder: "TextEmbedding | None" = None


def get_embedder() -> "TextEmbedding":
    global _embedder
    if _embedder is None:
        from fastembed import TextEmbedding
        cache_path = os.environ.get("FASTEMBED_CACHE_PATH")
        kwargs: dict[str, str] = {}
        if cache_path:
            kwargs["cache_dir"] = cache_path
        _embedder = TextEmbedding(_MODEL_NAME, **kwargs)
    return _embedder


def build_entity_text(
    entity: dict[str, Any],
    parent_labels: list[str],
    child_labels: list[str],
) -> str:
    parts: list[str] = []

    label = entity.get("primary_label") or entity.get("label") or entity.get("short", "")
    if label:
        parts.append(label + ".")

    raw_defs = entity.get("definitions", "[]")
    defs: list[dict[str, Any]] = json.loads(raw_defs) if isinstance(raw_defs, str) else raw_defs
    def_val = defs[0].get("value", "") if defs else ""
    if def_val:
        parts.append(def_val + ".")

    raw_syns = entity.get("synonyms", "[]")
    syns: list[dict[str, Any]] = json.loads(raw_syns) if isinstance(raw_syns, str) else raw_syns
    syn_vals = [s.get("value", "") for s in syns[:10] if s.get("value")]
    if syn_vals:
        parts.append("Synonyms: " + "; ".join(syn_vals) + ".")

    if parent_labels:
        parts.append("Superclasses: " + ", ".join(parent_labels[:5]) + ".")

    if child_labels:
        parts.append("Subclasses: " + ", ".join(child_labels[:10]) + ".")

    return " ".join(parts)


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def embed_texts(texts: list[str]) -> list[list[float]]:
    embedder = get_embedder()
    return [v.tolist() for v in embedder.passage_embed(texts, batch_size=64)]


def embed_query(text: str) -> list[float]:
    embedder = get_embedder()
    return next(embedder.query_embed([text])).tolist()  # type: ignore[return-value]
