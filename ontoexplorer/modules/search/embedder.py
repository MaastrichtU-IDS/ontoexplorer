from __future__ import annotations

import hashlib
import json
from typing import Any

from ontoexplorer.config import get_settings
from ontoexplorer.modules.search import embed_client

MODEL_REV = embed_client.MODEL_REV

# Memory safety for the embed worker (#229). the backend pads every batch to its
# longest sequence, so peak attention memory is O(batch_size x heads x seq^2). An
# uncapped definition (some ontologies carry ~12k-char / ~3k-token definitions)
# turned a batch of 128 into a tens-of-GiB allocation that OOM-killed worker-embed
# at its 32Gi limit — even on ontologies with only a few hundred entities. We bound
# both factors: cap each entity's text so no sequence is pathologically long, and
# use a smaller default batch. The retrieval signal lives in the label + head of
# the definition + synonyms, so the cap costs little recall. 2000 chars ~= 512
# tokens; 32 x 12 x 512^2 x 4 B ~= 0.4 GiB of attention, vs ~48 GiB before.
MAX_DEF_CHARS = 1000
MAX_ENTITY_TEXT_CHARS = 2000
EMBED_BATCH_SIZE = 32


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
    try:
        defs: list[dict[str, Any]] = json.loads(raw_defs) if raw_defs else []
    except (json.JSONDecodeError, ValueError):
        defs = [{"value": raw_defs, "lang": ""}]
    def_val = defs[0].get("value", "") if defs else ""
    if def_val:
        # Cap the definition: it is the usual source of a multi-thousand-token
        # sequence, and the head of a definition carries the retrieval signal (#229).
        if len(def_val) > MAX_DEF_CHARS:
            def_val = def_val[:MAX_DEF_CHARS].rstrip()
        parts.append(def_val + ".")

    raw_syns = entity.get("synonyms", "[]")
    try:
        syns: list[dict[str, Any]] = json.loads(raw_syns) if raw_syns else []
    except (json.JSONDecodeError, ValueError):
        # Old index format: plain pipe-delimited string
        syns = [{"value": s.strip(), "lang": ""} for s in raw_syns.split("|") if s.strip()]
    syn_vals = [s.get("value", "") for s in syns[:10] if s.get("value")]
    if syn_vals:
        parts.append("Synonyms: " + "; ".join(syn_vals) + ".")

    if parent_labels:
        parts.append("Superclasses: " + ", ".join(parent_labels[:5]) + ".")

    if child_labels:
        parts.append("Subclasses: " + ", ".join(child_labels[:10]) + ".")

    text = " ".join(parts)
    # Hard backstop so no single sequence can blow up batch attention memory,
    # whatever the field mix (#229). The per-field caps above usually keep us
    # well under this; this only bites a pathological combination.
    if len(text) > MAX_ENTITY_TEXT_CHARS:
        text = text[:MAX_ENTITY_TEXT_CHARS].rstrip()
    return text


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def embed_texts(texts: list[str], batch_size: int = EMBED_BATCH_SIZE) -> list[list[float]]:
    prefix = get_settings().embedding_doc_prefix
    out: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        out.extend(embed_client.embed_batch(texts[i : i + batch_size], prefix=prefix))
    return out


def embed_query(text: str) -> list[float]:
    return embed_client.embed_batch([text], prefix=get_settings().embedding_query_prefix)[0]
