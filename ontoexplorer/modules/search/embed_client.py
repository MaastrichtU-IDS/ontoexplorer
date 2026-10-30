"""Thin synchronous client for an OpenAI-compatible /v1/embeddings endpoint.

Primary (e.g. LiteLLM gateway) -> fallback (local llama.cpp) with retries,
batch splitting on "too large" errors, index-sorted responses, L2 normalisation.
"""

import logging
import math
import time

import httpx

from ontoexplorer.config import get_settings

logger = logging.getLogger(__name__)

MODEL_REV = "nomic-embed-text-v1.5-q8_0-gguf"

NUM_RETRIES = 2
_BACKOFF_S = (0.5, 1.0)

# Number of times the fallback host served a request (observability).
FALLBACK_COUNT = 0

_client = httpx.Client()

_TOO_LARGE_MARKERS = (
    "too large",
    "input is too long",
    "maximum context length",
    "context length",
    "batch size",
    "n_ubatch",
)


class EmbeddingError(Exception):
    pass


class _TooLarge(Exception):
    pass


class _HostError(Exception):
    pass


def _l2(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0.0:
        return list(vec)
    return [x / norm for x in vec]


def _is_too_large(resp: httpx.Response) -> bool:
    if resp.status_code == 413:
        return True
    if resp.status_code == 429:
        return False
    if resp.status_code >= 400:
        body = resp.text.lower()
        return any(m in body for m in _TOO_LARGE_MARKERS)
    return False


def _post_once(base_url: str, api_key: str, payload: dict, timeout: float) -> list[list[float]]:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        resp = _client.post(
            base_url.rstrip("/") + "/embeddings", json=payload, headers=headers, timeout=timeout
        )
    except httpx.HTTPError as e:
        raise _HostError(f"{base_url}: {e!r}") from e
    if resp.status_code == 200:
        try:
            data = sorted(resp.json()["data"], key=lambda d: d["index"])
            return [d["embedding"] for d in data]
        except (ValueError, KeyError, TypeError) as e:
            raise _HostError(f"{base_url}: malformed response: {e!r}") from e
    if _is_too_large(resp):
        raise _TooLarge(f"{base_url}: HTTP {resp.status_code}")
    err = _HostError(f"{base_url}: HTTP {resp.status_code}")
    err.retryable = resp.status_code == 429 or resp.status_code >= 500  # type: ignore[attr-defined]
    raise err


def _post(base_url: str, api_key: str, payload: dict, timeout: float, retries: int):
    attempt = 0
    while True:
        try:
            return _post_once(base_url, api_key, payload, timeout)
        except _HostError as e:
            retryable = getattr(e, "retryable", True)  # network errors are retryable
            if not retryable or attempt >= retries:
                raise
            time.sleep(_BACKOFF_S[min(attempt, len(_BACKOFF_S) - 1)])
            attempt += 1


def embed_batch(texts: list[str], *, prefix: str) -> list[list[float]]:
    global FALLBACK_COUNT
    if not texts:
        return []
    s = get_settings()
    payload = {"model": s.embedding_model, "input": [prefix + t for t in texts]}

    def _split() -> list[list[float]]:
        mid = len(texts) // 2
        return embed_batch(texts[:mid], prefix=prefix) + embed_batch(texts[mid:], prefix=prefix)

    vectors = None
    primary_err = None
    if s.embedding_base_url:
        try:
            vectors = _post(
                s.embedding_base_url, s.embedding_api_key, payload, s.embedding_timeout_s, NUM_RETRIES
            )
        except _TooLarge:
            if len(texts) > 1:
                return _split()
            primary_err = "single input too large"
        except _HostError as e:
            primary_err = str(e)

    if vectors is None:
        if s.embedding_base_url:
            FALLBACK_COUNT += 1
            logger.warning(
                "embedding primary failed (%s); using fallback (count=%d)", primary_err, FALLBACK_COUNT
            )
        try:
            vectors = _post(s.embedding_fallback_base_url, "", payload, s.embedding_fallback_timeout_s, 0)
        except _TooLarge as e:
            if len(texts) > 1:
                return _split()
            raise EmbeddingError(f"single input too large: {e}") from e
        except _HostError as e:
            raise EmbeddingError(f"embedding failed (primary: {primary_err}; fallback: {e})") from e

    if len(vectors) != len(texts):
        raise EmbeddingError(f"expected {len(texts)} vectors, got {len(vectors)}")
    for v in vectors:
        if len(v) != s.embedding_dim:
            raise EmbeddingError(f"embedding dim {len(v)} != expected {s.embedding_dim}")
    for v in vectors:
        if not any(v):
            raise EmbeddingError("degenerate (zero) embedding returned by backend")
    return [_l2(v) for v in vectors]
