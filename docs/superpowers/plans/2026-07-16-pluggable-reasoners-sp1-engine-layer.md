# Pluggable Reasoners — SP1 Engine Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the reasoning microservice's two-way `CLASSIFIER_BACKEND` switch into a capability-aware, reasoner-selectable engine — adding `rustdl` (classify + native justify) and `konclude` (classify + consistency) alongside the existing `whelk`/`rdflib` — and rename the service `elk-service` → `reasoner-service`.

**Architecture:** A `registry.py` module holds a `ReasonerInfo` (name/profile/capabilities/available) plus a `Backend` protocol (`classify_ntriples`, `justify`) per reasoner. `whelk`/`rdflib` are wrapped by thin adapters over the existing `whelk_classifier.py`/`classifier.py`; `rustdl_backend.py` calls the `owl-dl-py` PyO3 binding in-process; `konclude_backend.py` shells out to a bundled Konclude binary. `main.py` reads a `reasoner` field on each request, routes to the registry, and scopes Redis cache keys by reasoner. Everything is tested through the service's own HTTP API and unit tests.

**Tech Stack:** Python 3.12, FastAPI, pyoxigraph, py-horned-owl, py-whelk (existing), `rustdl` (owl-dl-py PyO3 wheel, new), Konclude prebuilt binary (new), Redis, pytest, Docker.

## Global Constraints

- Service directory `docker/elk-service/` → `docker/reasoner-service/`; compose service `elk-service` → `reasoner-service`. (Applies to every task that references a path under the service.)
- Image stays **amd64** (`platform: linux/amd64`); all reasoners run emulated on Apple Silicon, native on the Linux host. No native-arm64 work in SP1.
- The `ClassificationResult` dataclass shape is FROZEN and identical across all backends: `version_id, classified_at, class_count, superclasses, subclasses, direct_superclasses, direct_subclasses, unsatisfiable, proof_traces, duration_ms` (`classifier.py:52-62`). New backends populate the same fields; `proof_traces` may be `{}`.
- Reasoner names are the exact lowercase strings: `whelk`, `rdflib`, `rustdl`, `konclude`.
- Default reasoner when a request omits one: env `DEFAULT_REASONER`, defaulting to `whelk` (preserves today's behaviour). This is the *service-level* default; the app-level default is SP2.
- Justification response `format` field values: `"ntriples"` (whelk/rdflib) | `"manchester"` (rustdl).
- Tests that need an optional engine use `pytest.importorskip(...)` (rustdl) or skip when the Konclude binary is absent (`shutil.which`), mirroring `test_whelk_classifier.py:26`.
- Commits use `git -c user.email=michel.dumontier@gmail.com` and end with the `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>` trailer.
- HTTP contract changes are backward-compatible: omitting `reasoner` must behave exactly as today.

---

## File Structure

- `docker/reasoner-service/` — renamed service dir. Existing files kept: `main.py`, `cache.py`, `classifier.py`, `whelk_classifier.py`, `justification.py`, all `test_*.py`, `wheels/`, `Dockerfile`.
- **Create** `docker/reasoner-service/registry.py` — `Capability`, `ReasonerInfo`, `Backend` protocol, adapters for whelk/rdflib, `REGISTRY`, `get_backend`, `list_reasoners`, `default_reasoner`.
- **Create** `docker/reasoner-service/rustdl_backend.py` — rustdl classify + justify.
- **Create** `docker/reasoner-service/konclude_backend.py` — Konclude classify/consistency via subprocess.
- **Modify** `docker/reasoner-service/cache.py` — reasoner-scoped cache keys.
- **Modify** `docker/reasoner-service/main.py` — `reasoner` on requests, registry routing, `GET /reasoners`, justify routing + 422 + `format`.
- **Modify** `docker/reasoner-service/Dockerfile` — add rustdl wheel + Konclude binary; copy new source files.
- **Create** tests: `test_registry.py`, `test_reasoner_scoped_cache.py`, `test_rustdl_backend.py`, `test_konclude_backend.py`, `test_reasoners_endpoint.py`.
- **Modify (app side, for the rename only)** `ontoexplorer/config.py`, `ontoexplorer/clients/reasoning.py`, `ontoexplorer/api/health.py`, `ontoexplorer/api/admin/_common.py`, `ontoexplorer/api/admin/health.py`, `ontoexplorer/modules/jobs/tasks.py`, `docker-compose.yml`, `docker-compose.prod.yml`, `.env.example`.

---

## Task 1: Rename elk-service → reasoner-service

Mechanical rename confined to the service and its client wiring. No behaviour change.

**Files:**
- Move: `docker/elk-service/` → `docker/reasoner-service/` (all files)
- Modify: `docker-compose.yml` (service block ~`:142`, `depends_on` ~`:19`), `docker-compose.prod.yml`
- Modify: `ontoexplorer/config.py:57` (`elk_service_url`, `elk_service_timeout`), `ontoexplorer/clients/reasoning.py:28`, `ontoexplorer/api/health.py:59`, `ontoexplorer/api/admin/_common.py:53`, `ontoexplorer/api/admin/health.py:52`, `ontoexplorer/modules/jobs/tasks.py:479`
- Modify: `.env.example:85-86`

**Interfaces:**
- Consumes: nothing (first task)
- Produces: config settings `reasoner_service_url: str` (default `http://localhost:8001`) and `reasoner_service_timeout: int` (default `3600`), read via `get_settings()`. All later app-side code uses these names.

- [ ] **Step 1: Move the directory with git**

```bash
cd ~/code/ontoexplorer
git mv docker/elk-service docker/reasoner-service
```

- [ ] **Step 2: Verify the service tests still pass under the new path**

Run: `cd docker/reasoner-service && python -m pytest test_classifier.py -q`
Expected: PASS (pure-Python legacy tests need no extension); whelk tests may skip if `pywhelk` absent — that's fine.

- [ ] **Step 3: Rename the compose service and dependency**

In `docker-compose.yml`: rename the `elk-service:` service key to `reasoner-service:`, update its `build:` context to `docker/reasoner-service`, and in the `api`/worker `depends_on` lists change `elk-service` → `reasoner-service`. Do the same in `docker-compose.prod.yml`. Leave `docker-compose.override.yml` for the reader's local edit (it is gitignored).

- [ ] **Step 4: Rename the config settings**

In `ontoexplorer/config.py:57`, rename `elk_service_url` → `reasoner_service_url` and `elk_service_timeout` → `reasoner_service_timeout`. Add backward-compatible env aliases so existing `.env` files keep working for one release:

```python
    reasoner_service_url: str = Field(
        default="http://localhost:8001",
        validation_alias=AliasChoices("REASONER_SERVICE_URL", "ELK_SERVICE_URL"),
    )
    reasoner_service_timeout: int = Field(
        default=3600,
        validation_alias=AliasChoices("REASONER_SERVICE_TIMEOUT", "ELK_SERVICE_TIMEOUT"),
    )
```

(Import `AliasChoices` and `Field` from `pydantic` if not already imported. If the settings class does not use `Field`, follow the file's existing pattern and add the aliases the way that class reads env — the requirement is: both new and old env names resolve.)

- [ ] **Step 5: Update all app-side references**

Replace `settings.elk_service_url` → `settings.reasoner_service_url` and `settings.elk_service_timeout` → `settings.reasoner_service_timeout` in: `clients/reasoning.py`, `api/health.py`, `api/admin/_common.py`, `api/admin/health.py`, `modules/jobs/tasks.py`. Grep to confirm none remain:

```bash
cd ~/code/ontoexplorer && grep -rn "elk_service" ontoexplorer/ ; echo "exit:$?"
```
Expected: no matches (grep exit 1).

- [ ] **Step 6: Update .env.example**

In `.env.example`, rename `ELK_SERVICE_URL=http://elk-service:8001` → `REASONER_SERVICE_URL=http://reasoner-service:8001` and `ELK_SERVICE_TIMEOUT=3600` → `REASONER_SERVICE_TIMEOUT=3600`. Add a comment line: `# (ELK_SERVICE_URL / ELK_SERVICE_TIMEOUT accepted as deprecated aliases)`.

- [ ] **Step 7: Add a config alias test**

Create `tests/test_reasoner_service_config_alias.py`:

```python
import importlib
from ontoexplorer.config import get_settings


def test_new_env_name_wins(monkeypatch):
    monkeypatch.setenv("REASONER_SERVICE_URL", "http://reasoner-service:8001")
    get_settings.cache_clear()
    assert get_settings().reasoner_service_url == "http://reasoner-service:8001"


def test_old_env_alias_still_works(monkeypatch):
    monkeypatch.delenv("REASONER_SERVICE_URL", raising=False)
    monkeypatch.setenv("ELK_SERVICE_URL", "http://legacy:8001")
    get_settings.cache_clear()
    assert get_settings().reasoner_service_url == "http://legacy:8001"
```

(If `get_settings` is not an `lru_cache`d function with `.cache_clear()`, adapt to how the project constructs settings — check `config.py` for the memoisation pattern.)

- [ ] **Step 8: Run the alias test**

Run: `cd ~/code/ontoexplorer && python -m pytest tests/test_reasoner_service_config_alias.py -q`
Expected: PASS (2 passed).

- [ ] **Step 9: Commit**

```bash
cd ~/code/ontoexplorer
git add -A
git -c user.email=michel.dumontier@gmail.com commit -m "refactor: rename elk-service -> reasoner-service

Directory, compose service, config settings, and app client references.
ELK_SERVICE_URL / ELK_SERVICE_TIMEOUT kept as deprecated env aliases.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Reasoner-scoped cache keys

Make Redis cache keys include the reasoner so results from different reasoners on the same version don't collide, keeping omit-reasoner behaviour backward-compatible via a `whelk` default sentinel is NOT used — instead the key always includes the resolved reasoner name.

**Files:**
- Modify: `docker/reasoner-service/cache.py`
- Test: `docker/reasoner-service/test_reasoner_scoped_cache.py`

**Interfaces:**
- Consumes: `ClassificationResult` (has `version_id`); callers now pass a `reasoner: str`.
- Produces: cache functions gain a trailing `reasoner: str` parameter:
  - `store_classification(result, reasoner)`, `load_classification(version_id, reasoner) -> ClassificationResult | None`
  - `store_input_axioms(version_id, ntriples, reasoner)`, `load_input_axioms(version_id, reasoner) -> str | None`
  - `store_classification_error(version_id, message, reasoner)`, `load_classification_error(version_id, reasoner) -> str | None`, `clear_classification_error(version_id, reasoner)`
  - `store_justification(version_id, sub, sup, max_j, reasoner, result)`, `load_justification(version_id, sub, sup, max_j, reasoner) -> dict | None`
  - `invalidate_version(version_id)` unchanged in signature; must now clear ALL reasoner variants for the version.

- [ ] **Step 1: Write the failing test**

Create `docker/reasoner-service/test_reasoner_scoped_cache.py`:

```python
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import fakeredis
import pytest
import cache as cache_mod
from classifier import ClassificationResult


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch):
    r = fakeredis.FakeStrictRedis()
    monkeypatch.setattr(cache_mod, "_redis", r)
    return r


def _result(vid="v1"):
    return ClassificationResult(
        version_id=vid, classified_at="t", class_count=0,
        superclasses={}, subclasses={}, direct_superclasses={},
        direct_subclasses={}, unsatisfiable=[], proof_traces={}, duration_ms=1.0,
    )


def test_two_reasoners_do_not_collide():
    cache_mod.store_classification(_result("v1"), "whelk")
    cache_mod.store_classification(_result("v1"), "rustdl")
    # Overwriting under rustdl must not affect whelk's entry.
    assert cache_mod.load_classification("v1", "whelk") is not None
    assert cache_mod.load_classification("v1", "rustdl") is not None
    assert cache_mod.load_classification("v1", "konclude") is None


def test_invalidate_clears_all_reasoner_variants():
    cache_mod.store_classification(_result("v1"), "whelk")
    cache_mod.store_classification(_result("v1"), "rustdl")
    cache_mod.store_input_axioms("v1", "<a> <b> <c> .", "whelk")
    cache_mod.invalidate_version("v1")
    assert cache_mod.load_classification("v1", "whelk") is None
    assert cache_mod.load_classification("v1", "rustdl") is None
    assert cache_mod.load_input_axioms("v1", "whelk") is None


def test_justification_scoped_by_reasoner():
    cache_mod.store_justification("v1", "sub", "sup", 3, "rustdl", {"ok": True})
    assert cache_mod.load_justification("v1", "sub", "sup", 3, "rustdl") == {"ok": True}
    assert cache_mod.load_justification("v1", "sub", "sup", 3, "whelk") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd docker/reasoner-service && python -m pytest test_reasoner_scoped_cache.py -q`
Expected: FAIL (`store_classification()` takes 1 positional arg / TypeError).

- [ ] **Step 3: Add fakeredis to the test toolchain**

Run: `pip install fakeredis`
(fakeredis is a test-only dependency; it is not added to the image.)

- [ ] **Step 4: Rewrite cache.py key builders and signatures**

Replace the key builders and all public functions in `docker/reasoner-service/cache.py` so every key embeds the reasoner:

```python
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


def store_classification(result: ClassificationResult, reasoner: str) -> None:
    key = _classification_key(result.version_id, reasoner)
    data = json.dumps(asdict(result)).encode()
    _redis.setex(key, _CLASSIFICATION_TTL, gzip.compress(data))
    clear_classification_error(result.version_id, reasoner)


def load_classification(version_id: str, reasoner: str) -> ClassificationResult | None:
    raw = _redis.get(_classification_key(version_id, reasoner))
    if raw is None:
        return None
    return ClassificationResult(**json.loads(gzip.decompress(raw)))


def store_justification(version_id, sub, sup, max_j, reasoner, result: dict) -> None:
    _redis.setex(_justification_key(version_id, sub, sup, max_j, reasoner),
                 _JUSTIFICATION_TTL, json.dumps(result).encode())


def load_justification(version_id, sub, sup, max_j, reasoner) -> dict | None:
    raw = _redis.get(_justification_key(version_id, sub, sup, max_j, reasoner))
    return json.loads(raw) if raw else None


def store_input_axioms(version_id: str, ntriples: str, reasoner: str) -> None:
    _redis.setex(_input_axioms_key(version_id, reasoner),
                 _CLASSIFICATION_TTL, gzip.compress(ntriples.encode("utf-8")))


def load_input_axioms(version_id: str, reasoner: str) -> str | None:
    raw = _redis.get(_input_axioms_key(version_id, reasoner))
    return gzip.decompress(raw).decode("utf-8") if raw is not None else None


def store_classification_error(version_id: str, message: str, reasoner: str) -> None:
    _redis.setex(_classification_error_key(version_id, reasoner),
                 _CLASSIFICATION_TTL, message.encode("utf-8"))


def load_classification_error(version_id: str, reasoner: str) -> str | None:
    raw = _redis.get(_classification_error_key(version_id, reasoner))
    return raw.decode("utf-8") if raw else None


def clear_classification_error(version_id: str, reasoner: str) -> None:
    _redis.delete(_classification_error_key(version_id, reasoner))


def invalidate_version(version_id: str) -> None:
    """Remove ALL cache entries for a version across every reasoner variant."""
    keys = set()
    for pat in (f"classification:{version_id}:*", f"input_axioms:{version_id}:*",
                f"classification_error:{version_id}:*", f"justification:{version_id}:*"):
        keys.update(_redis.scan_iter(pat))
    if keys:
        _redis.delete(*keys)
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd docker/reasoner-service && python -m pytest test_reasoner_scoped_cache.py -q`
Expected: PASS (3 passed).

- [ ] **Step 6: Commit**

```bash
cd ~/code/ontoexplorer
git add docker/reasoner-service/cache.py docker/reasoner-service/test_reasoner_scoped_cache.py
git -c user.email=michel.dumontier@gmail.com commit -m "feat(reasoner-service): scope Redis cache keys by reasoner

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Reasoner registry + whelk/rdflib adapters

Introduce the registry and wrap the two existing backends behind it. No new reasoners yet — this locks the interface.

**Files:**
- Create: `docker/reasoner-service/registry.py`
- Test: `docker/reasoner-service/test_registry.py`

**Interfaces:**
- Consumes: `whelk_classifier.classify_ntriples`, `classifier.classify` (legacy, takes rdflib graph — the whelk adapter uses `classify_ntriples`; the rdflib adapter parses NT to a graph first), `justification.compute_justifications`.
- Produces:
  - `Capability = Literal["classify","consistency","justify","diagnose","repair"]`
  - `@dataclass(frozen=True) class ReasonerInfo: name: str; profile: str; capabilities: frozenset[str]; available: bool`
  - `class Backend(Protocol)` with `info: ReasonerInfo`, `classify_ntriples(ntriples: str, version_id: str) -> ClassificationResult`, and `justify(ntriples: str, sub: str, sup: str, max_justifications: int) -> tuple[list[list[str]], str]` returning `(justification_sets, format)` where `format` ∈ `{"ntriples","manchester"}`. Backends without the `justify` capability raise `NotImplementedError`.
  - `get_backend(name: str) -> Backend` (raises `KeyError` for unknown), `list_reasoners() -> list[ReasonerInfo]`, `default_reasoner() -> str` (env `DEFAULT_REASONER`, fallback `"whelk"`).

- [ ] **Step 1: Write the failing test**

Create `docker/reasoner-service/test_registry.py`:

```python
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import pytest
import registry


def test_all_four_reasoners_registered():
    names = {r.name for r in registry.list_reasoners()}
    assert {"whelk", "rdflib", "rustdl", "konclude"} <= names


def test_capabilities_are_correct():
    caps = {r.name: r.capabilities for r in registry.list_reasoners()}
    assert "justify" in caps["whelk"]
    assert "justify" in caps["rustdl"]
    assert "justify" not in caps["konclude"]      # Konclude cannot explain
    assert "classify" in caps["konclude"]


def test_default_reasoner_env(monkeypatch):
    monkeypatch.delenv("DEFAULT_REASONER", raising=False)
    assert registry.default_reasoner() == "whelk"
    monkeypatch.setenv("DEFAULT_REASONER", "rustdl")
    assert registry.default_reasoner() == "rustdl"


def test_unknown_backend_raises():
    with pytest.raises(KeyError):
        registry.get_backend("hermit")


def test_konclude_justify_raises_not_implemented():
    with pytest.raises(NotImplementedError):
        registry.get_backend("konclude").justify("", "s", "o", 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd docker/reasoner-service && python -m pytest test_registry.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'registry'`).

- [ ] **Step 3: Write registry.py**

Create `docker/reasoner-service/registry.py`:

```python
"""Capability-aware reasoner registry for reasoner-service.

Each reasoner is a Backend: it classifies N-Triples into a ClassificationResult
and (optionally) computes justifications. Capabilities let the HTTP layer and
the app decide what a given reasoner can do (e.g. Konclude cannot justify).
"""
from __future__ import annotations

import io
import os
from dataclasses import dataclass
from typing import Literal, Protocol

import rdflib

from classifier import ClassificationResult

Capability = Literal["classify", "consistency", "justify", "diagnose", "repair"]


@dataclass(frozen=True)
class ReasonerInfo:
    name: str
    profile: str
    capabilities: frozenset[str]
    available: bool


class Backend(Protocol):
    info: ReasonerInfo

    def classify_ntriples(self, ntriples: str, version_id: str) -> ClassificationResult: ...

    def justify(self, ntriples: str, sub: str, sup: str,
                max_justifications: int) -> tuple[list[list[str]], str]: ...


# ── whelk ──────────────────────────────────────────────────────────────────
class _WhelkBackend:
    info = ReasonerInfo(
        name="whelk", profile="EL",
        capabilities=frozenset({"classify", "consistency", "justify"}),
        available=_import_ok("pywhelk"),
    )

    def classify_ntriples(self, ntriples, version_id):
        from whelk_classifier import classify_ntriples
        return classify_ntriples(ntriples, version_id)

    def justify(self, ntriples, sub, sup, max_justifications):
        from classifier import ClassificationResult as _CR  # noqa: F401
        from justification import compute_justifications
        g = rdflib.Graph()
        g.parse(io.StringIO(ntriples), format="nt")
        # compute_justifications needs the ClassificationResult only for its
        # proof_traces fallback; a minimal result with the input graph suffices
        # because the greedy walk re-derives entailment from the graph itself.
        empty = _empty_result(version_id="_justify")
        sets = compute_justifications(g, empty, sub, sup, max_justifications)
        return sets, "ntriples"


# ── rdflib (legacy) ──────────────────────────────────────────────────────────
class _RdflibBackend:
    info = ReasonerInfo(
        name="rdflib", profile="EL (legacy)",
        capabilities=frozenset({"classify", "consistency"}),
        available=True,
    )

    def classify_ntriples(self, ntriples, version_id):
        from classifier import classify
        g = rdflib.Graph()
        g.parse(io.StringIO(ntriples), format="nt")
        return classify(g, version_id)

    def justify(self, ntriples, sub, sup, max_justifications):
        raise NotImplementedError("rdflib backend does not expose justifications in SP1")


def _empty_result(version_id: str) -> ClassificationResult:
    return ClassificationResult(
        version_id=version_id, classified_at="", class_count=0,
        superclasses={}, subclasses={}, direct_superclasses={},
        direct_subclasses={}, unsatisfiable=[], proof_traces={}, duration_ms=0.0,
    )


def _import_ok(mod: str) -> bool:
    import importlib.util
    return importlib.util.find_spec(mod) is not None


# Backends registered lazily so importing rustdl/konclude modules (which may be
# absent) does not break the registry import.
def _build_registry() -> dict[str, Backend]:
    reg: dict[str, Backend] = {"whelk": _WhelkBackend(), "rdflib": _RdflibBackend()}
    from rustdl_backend import RustdlBackend
    from konclude_backend import KoncludeBackend
    reg["rustdl"] = RustdlBackend()
    reg["konclude"] = KoncludeBackend()
    return reg


_REGISTRY: dict[str, Backend] | None = None


def _registry() -> dict[str, Backend]:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = _build_registry()
    return _REGISTRY


def get_backend(name: str) -> Backend:
    return _registry()[name]


def list_reasoners() -> list[ReasonerInfo]:
    return [b.info for b in _registry().values()]


def default_reasoner() -> str:
    return os.getenv("DEFAULT_REASONER", "whelk")
```

Note: `whelk` `justify` reuses `compute_justifications` from `justification.py`, which reconstructs entailment from the input graph (its `_load_input_graph` path already works off cached input axioms — here we pass the graph directly). If `compute_justifications`'s signature differs, call it exactly as `main.py:240` does (`compute_justifications(g, result, sub, sup, max)`); the `result` arg only feeds a proof-trace fallback and an empty result is acceptable.

- [ ] **Step 4: Create backend module stubs so the registry imports**

Create `docker/reasoner-service/rustdl_backend.py` (filled in Task 4):

```python
"""rustdl backend (owl-dl-py PyO3 binding). Classify + native justify."""
from __future__ import annotations

import importlib.util
from registry import ReasonerInfo
from classifier import ClassificationResult


class RustdlBackend:
    info = ReasonerInfo(
        name="rustdl", profile="DL (SROIQ)",
        capabilities=frozenset({"classify", "consistency", "justify"}),
        available=importlib.util.find_spec("rustdl") is not None,
    )

    def classify_ntriples(self, ntriples: str, version_id: str) -> ClassificationResult:
        raise NotImplementedError  # Task 4

    def justify(self, ntriples, sub, sup, max_justifications):
        raise NotImplementedError  # Task 5
```

Create `docker/reasoner-service/konclude_backend.py` (filled in Task 6):

```python
"""Konclude backend (prebuilt binary subprocess). Classify + consistency only."""
from __future__ import annotations

import shutil
from registry import ReasonerInfo
from classifier import ClassificationResult

_KONCLUDE_BIN = shutil.which("Konclude")


class KoncludeBackend:
    info = ReasonerInfo(
        name="konclude", profile="OWL 2 (all profiles)",
        capabilities=frozenset({"classify", "consistency"}),
        available=_KONCLUDE_BIN is not None,
    )

    def classify_ntriples(self, ntriples: str, version_id: str) -> ClassificationResult:
        raise NotImplementedError  # Task 6

    def justify(self, ntriples, sub, sup, max_justifications):
        raise NotImplementedError("Konclude has no justification facility")
```

There is a circular import: `registry._build_registry` imports the backend modules, which import `ReasonerInfo` from `registry`. This is safe because `_build_registry` is only called at first use (after `registry` is fully imported), not at import time. Verify Step 5 passes to confirm.

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd docker/reasoner-service && python -m pytest test_registry.py -q`
Expected: PASS (5 passed). `available` flags will be `False` where the engine isn't installed locally — the tests assert capabilities, not availability.

- [ ] **Step 6: Commit**

```bash
cd ~/code/ontoexplorer
git add docker/reasoner-service/registry.py docker/reasoner-service/rustdl_backend.py docker/reasoner-service/konclude_backend.py docker/reasoner-service/test_registry.py
git -c user.email=michel.dumontier@gmail.com commit -m "feat(reasoner-service): capability-aware reasoner registry + whelk/rdflib adapters

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: rustdl classification backend

Fill in `RustdlBackend.classify_ntriples` using the `owl-dl-py` binding.

**Files:**
- Modify: `docker/reasoner-service/rustdl_backend.py`
- Test: `docker/reasoner-service/test_rustdl_backend.py`

**Interfaces:**
- Consumes: `rustdl.classify_bytes(data: bytes, *, format: str, per_pair_timeout_ms, global_deadline_ms, saturation_only)` → object with `.classes -> list[str]`, `.unsatisfiable -> list[str]`, `.inconsistent -> bool`, `.direct_subsumers(c) -> list[str]`, `.superclasses_of(c) -> list[str]`, `.complete -> bool`; the NT→RDF/XML conversion helper pattern from `whelk_classifier.classify_ntriples` (pyoxigraph Store → `serialize(..., RDF_XML)`).
- Produces: a populated `ClassificationResult` with the frozen field set.

- [ ] **Step 1: Write the failing test**

Create `docker/reasoner-service/test_rustdl_backend.py`:

```python
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import pytest

pytest.importorskip("rustdl")
pytest.importorskip("pyoxigraph")
from rustdl_backend import RustdlBackend

EX = "http://example.org/"
NT = f"""\
<{EX}A> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://www.w3.org/2002/07/owl#Class> .
<{EX}B> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://www.w3.org/2002/07/owl#Class> .
<{EX}C> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://www.w3.org/2002/07/owl#Class> .
<{EX}A> <http://www.w3.org/2000/01/rdf-schema#subClassOf> <{EX}B> .
<{EX}B> <http://www.w3.org/2000/01/rdf-schema#subClassOf> <{EX}C> .
"""


def test_transitive_superclass_inferred_not_asserted():
    r = RustdlBackend().classify_ntriples(NT, "v-test")
    sups = r.superclasses.get(f"{EX}A", [])
    assert f"{EX}C" in sups          # inferred transitive
    assert f"{EX}B" not in sups      # asserted, excluded from inferred set
    assert r.direct_superclasses.get(f"{EX}A", []) == [f"{EX}B"]


def test_result_has_frozen_field_shape():
    r = RustdlBackend().classify_ntriples(NT, "v-test")
    for field in ("version_id", "classified_at", "class_count", "superclasses",
                  "subclasses", "direct_superclasses", "direct_subclasses",
                  "unsatisfiable", "proof_traces", "duration_ms"):
        assert hasattr(r, field)
    assert r.proof_traces == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd docker/reasoner-service && python -m pytest test_rustdl_backend.py -q`
Expected: FAIL (`NotImplementedError`), or SKIP if `rustdl` is not installed locally. If skipped, build the wheel first: `cd ~/code/rustdl && maturin build --release -m crates/owl-dl-py/Cargo.toml && pip install target/wheels/rustdl-*.whl`, then re-run — it must FAIL, not skip.

- [ ] **Step 3: Implement classify_ntriples**

Replace the `classify_ntriples` body in `rustdl_backend.py`:

```python
    def classify_ntriples(self, ntriples: str, version_id: str) -> ClassificationResult:
        import io, time, os
        from collections import defaultdict
        from datetime import datetime, timezone
        import pyoxigraph
        import rustdl

        OWL_THING = "http://www.w3.org/2002/07/owl#Thing"
        OWL_NOTHING = "http://www.w3.org/2002/07/owl#Nothing"
        t0 = time.monotonic()

        # NT -> RDF/XML (same conversion whelk_classifier uses).
        store = pyoxigraph.Store()
        store.bulk_load(io.BytesIO(ntriples.encode("utf-8")),
                        format=pyoxigraph.RdfFormat.N_TRIPLES)
        rdfxml = pyoxigraph.serialize(
            (q.triple for q in store.quads_for_pattern(None, None, None, None)),
            format=pyoxigraph.RdfFormat.RDF_XML,
        )

        cls = rustdl.classify_bytes(
            rdfxml, format="rdf-xml",
            per_pair_timeout_ms=int(os.getenv("RUSTDL_PER_PAIR_TIMEOUT_MS", "200")),
            global_deadline_ms=int(os.getenv("RUSTDL_GLOBAL_DEADLINE_MS", "60000")),
        )

        # Asserted subClassOf pairs (to exclude from the inferred `superclasses`).
        RDFS_SUB = pyoxigraph.NamedNode("http://www.w3.org/2000/01/rdf-schema#subClassOf")
        asserted: set[tuple[str, str]] = set()
        direct_sup: dict[str, list[str]] = defaultdict(list)
        for q in store.quads_for_pattern(None, RDFS_SUB, None, None):
            if isinstance(q.subject, pyoxigraph.NamedNode) and isinstance(q.object, pyoxigraph.NamedNode):
                if q.subject.value != q.object.value:
                    asserted.add((q.subject.value, q.object.value))
                    direct_sup[q.subject.value].append(q.object.value)

        classes = [c for c in cls.classes if c not in (OWL_THING, OWL_NOTHING)]
        superclasses: dict[str, list[str]] = {}
        for c in classes:
            inferred = [s for s in cls.superclasses_of(c)
                        if s != c and s not in (OWL_THING,) and (c, s) not in asserted]
            if inferred:
                superclasses[c] = inferred

        subclasses: dict[str, list[str]] = defaultdict(list)
        for c, sups in superclasses.items():
            for s in sups:
                subclasses[s].append(c)

        direct_subs: dict[str, list[str]] = defaultdict(list)
        for c, sups in direct_sup.items():
            for s in sups:
                direct_subs[s].append(c)

        if not cls.complete:
            import logging
            logging.getLogger("reasoner-service").warning(
                "rustdl_incomplete version_id=%s timed_out_pairs=%s",
                version_id, cls.timed_out_pairs)

        return ClassificationResult(
            version_id=version_id,
            classified_at=datetime.now(timezone.utc).isoformat(),
            class_count=len(classes),
            superclasses=dict(superclasses),
            subclasses=dict(subclasses),
            direct_superclasses={k: sorted(v) for k, v in direct_sup.items()},
            direct_subclasses=dict(direct_subs),
            unsatisfiable=list(cls.unsatisfiable),
            proof_traces={},
            duration_ms=round((time.monotonic() - t0) * 1000, 1),
        )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd docker/reasoner-service && python -m pytest test_rustdl_backend.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
cd ~/code/ontoexplorer
git add docker/reasoner-service/rustdl_backend.py docker/reasoner-service/test_rustdl_backend.py
git -c user.email=michel.dumontier@gmail.com commit -m "feat(reasoner-service): rustdl classification backend via owl-dl-py

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: rustdl justification

Fill in `RustdlBackend.justify` using `rustdl.justify(path, query)`.

**Files:**
- Modify: `docker/reasoner-service/rustdl_backend.py`
- Test: `docker/reasoner-service/test_rustdl_backend.py` (extend)

**Interfaces:**
- Consumes: `rustdl.justify(path: str, query: list[str]) -> list[str]` (one minimal justification as Manchester axiom strings; query tokens `["subclass", sub, sup]` or `["unsat", c]`); `rustdl.justify_all(path, query, max) -> list[list[str]]`.
- Produces: `justify(ntriples, sub, sup, max_justifications) -> (list[list[str]], "manchester")`.

- [ ] **Step 1: Write the failing test (append to test_rustdl_backend.py)**

```python
def test_justify_returns_manchester_axiom_set():
    sets, fmt = RustdlBackend().justify(NT, f"{EX}A", f"{EX}C", 1)
    assert fmt == "manchester"
    assert len(sets) >= 1
    joined = " ".join(sets[0])
    # The A⊑B, B⊑C axioms are the responsible set for A⊑C.
    assert "A" in joined and "B" in joined and "C" in joined
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd docker/reasoner-service && python -m pytest test_rustdl_backend.py::test_justify_returns_manchester_axiom_set -q`
Expected: FAIL (`NotImplementedError`).

- [ ] **Step 3: Implement justify**

Replace the `justify` body in `rustdl_backend.py`:

```python
    def justify(self, ntriples: str, sub: str, sup: str,
                max_justifications: int) -> tuple[list[list[str]], str]:
        import io, os, tempfile
        import pyoxigraph
        import rustdl

        OWL_NOTHING = "http://www.w3.org/2002/07/owl#Nothing"

        # rustdl.justify takes a file path; materialise the NT as RDF/XML (.rdf).
        store = pyoxigraph.Store()
        store.bulk_load(io.BytesIO(ntriples.encode("utf-8")),
                        format=pyoxigraph.RdfFormat.N_TRIPLES)
        rdfxml = pyoxigraph.serialize(
            (q.triple for q in store.quads_for_pattern(None, None, None, None)),
            format=pyoxigraph.RdfFormat.RDF_XML,
        )
        fd, path = tempfile.mkstemp(suffix=".rdf")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(rdfxml)
            query = ["unsat", sub] if sup == OWL_NOTHING else ["subclass", sub, sup]
            if max_justifications == 1:
                one = rustdl.justify(path, query)
                sets = [one] if one else []
            else:
                sets = rustdl.justify_all(path, query, max_justifications)
            return sets, "manchester"
        finally:
            os.unlink(path)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd docker/reasoner-service && python -m pytest test_rustdl_backend.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
cd ~/code/ontoexplorer
git add docker/reasoner-service/rustdl_backend.py docker/reasoner-service/test_rustdl_backend.py
git -c user.email=michel.dumontier@gmail.com commit -m "feat(reasoner-service): rustdl native justifications (Manchester)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Konclude classification backend (subprocess)

Fill in `KoncludeBackend.classify_ntriples` by shelling out to the bundled Konclude binary. Konclude wants OWL/XML input and writes inferred axioms as OWL/XML.

**Files:**
- Modify: `docker/reasoner-service/konclude_backend.py`
- Test: `docker/reasoner-service/test_konclude_backend.py`

**Interfaces:**
- Consumes: `Konclude classification -w AUTO -i <in.owx> -o <out.owx>` (invocation confirmed from rustdl `scripts/konclude-oracle.sh:22`); NT→OWL/XML via `pyhornedowl.open_ontology_from_string(rdfxml, serialization="rdf")` then `save_to_string(serialization="owx")` (confirm the exact py-horned-owl serialisation keyword — see whelk_classifier's `open_ontology_from_string` usage at `whelk_classifier.py:67`); output parsed with pyoxigraph/rdflib for inferred `SubClassOf` / `owl:Nothing` edges.
- Produces: a populated `ClassificationResult` (`proof_traces={}`, since Konclude gives no traces).

- [ ] **Step 1: Write the failing test**

Create `docker/reasoner-service/test_konclude_backend.py`:

```python
import sys, os, shutil
sys.path.insert(0, os.path.dirname(__file__))

import pytest

if shutil.which("Konclude") is None:
    pytest.skip("Konclude binary not on PATH", allow_module_level=True)
pytest.importorskip("pyhornedowl")
pytest.importorskip("pyoxigraph")
from konclude_backend import KoncludeBackend

EX = "http://example.org/"
NT = f"""\
<{EX}A> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://www.w3.org/2002/07/owl#Class> .
<{EX}B> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://www.w3.org/2002/07/owl#Class> .
<{EX}C> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://www.w3.org/2002/07/owl#Class> .
<{EX}A> <http://www.w3.org/2000/01/rdf-schema#subClassOf> <{EX}B> .
<{EX}B> <http://www.w3.org/2000/01/rdf-schema#subClassOf> <{EX}C> .
"""


def test_konclude_infers_transitive_superclass():
    r = KoncludeBackend().classify_ntriples(NT, "v-test")
    assert f"{EX}C" in r.superclasses.get(f"{EX}A", [])
    assert r.proof_traces == {}
```

- [ ] **Step 2: Run test to verify it fails or skips**

Run: `cd docker/reasoner-service && python -m pytest test_konclude_backend.py -q`
Expected: SKIP locally if no `Konclude` on PATH. To exercise it, extract the binary from the image: `docker create --name k konclude/konclude:latest && docker cp k:$(docker run --rm konclude/konclude:latest which Konclude 2>/dev/null || echo /Konclude/Binaries/Konclude) ./Konclude && docker rm k && sudo mv Konclude /usr/local/bin/`. Then re-run — it must FAIL (`NotImplementedError`).

- [ ] **Step 3: Implement classify_ntriples**

Replace the `classify_ntriples` body in `konclude_backend.py`:

```python
    def classify_ntriples(self, ntriples: str, version_id: str) -> ClassificationResult:
        import io, time, tempfile, subprocess, os
        from collections import defaultdict
        from datetime import datetime, timezone
        import pyoxigraph
        import pyhornedowl
        import rdflib

        OWL_THING = "http://www.w3.org/2002/07/owl#Thing"
        OWL_NOTHING = "http://www.w3.org/2002/07/owl#Nothing"
        RDFS_SUB = rdflib.RDFS.subClassOf
        t0 = time.monotonic()

        # NT -> RDF/XML -> OWL/XML (Konclude reads OWL/XML).
        store = pyoxigraph.Store()
        store.bulk_load(io.BytesIO(ntriples.encode("utf-8")),
                        format=pyoxigraph.RdfFormat.N_TRIPLES)
        rdfxml = pyoxigraph.serialize(
            (q.triple for q in store.quads_for_pattern(None, None, None, None)),
            format=pyoxigraph.RdfFormat.RDF_XML,
        ).decode("utf-8")
        onto = pyhornedowl.open_ontology_from_string(rdfxml, serialization="rdf")
        owx = onto.save_to_string(serialization="owx")

        tmp = tempfile.mkdtemp()
        in_owx, out_owx = os.path.join(tmp, "in.owx"), os.path.join(tmp, "out.owx")
        try:
            with open(in_owx, "w") as fh:
                fh.write(owx)
            subprocess.run([os.getenv("KONCLUDE_BIN", "Konclude"),
                            "classification", "-w", "AUTO", "-i", in_owx, "-o", out_owx],
                           check=True, capture_output=True, timeout=600)

            # Parse Konclude's inferred output (OWL/XML) back into an rdflib graph.
            inferred = pyhornedowl.open_ontology_from_file(out_owx)
            inferred_rdf = inferred.save_to_string(serialization="rdf")
            g = rdflib.Graph()
            g.parse(io.StringIO(inferred_rdf), format="xml")
        finally:
            import shutil as _sh
            _sh.rmtree(tmp, ignore_errors=True)

        asserted: set[tuple[str, str]] = set()
        classes: set[str] = set()
        for s, _, o in store.quads_for_pattern(  # asserted edges from input
                None, pyoxigraph.NamedNode(str(RDFS_SUB)), None, None) and []:
            pass  # replaced below

        # Collect asserted subClassOf from the input store.
        RDFS_SUB_NN = pyoxigraph.NamedNode(str(RDFS_SUB))
        direct_sup: dict[str, list[str]] = defaultdict(list)
        for q in store.quads_for_pattern(None, RDFS_SUB_NN, None, None):
            if isinstance(q.subject, pyoxigraph.NamedNode) and isinstance(q.object, pyoxigraph.NamedNode):
                classes.add(q.subject.value); classes.add(q.object.value)
                if q.subject.value != q.object.value:
                    asserted.add((q.subject.value, q.object.value))
                    direct_sup[q.subject.value].append(q.object.value)

        superclasses: dict[str, list[str]] = defaultdict(list)
        unsatisfiable: list[str] = []
        for s, _, o in g.triples((None, RDFS_SUB, None)):
            if not (isinstance(s, rdflib.URIRef) and isinstance(o, rdflib.URIRef)):
                continue
            su, ob = str(s), str(o)
            if ob == OWL_NOTHING and su != OWL_NOTHING:
                if su not in unsatisfiable:
                    unsatisfiable.append(su)
                continue
            if su == ob or ob == OWL_THING or (su, ob) in asserted:
                continue
            superclasses[su].append(ob)

        subclasses: dict[str, list[str]] = defaultdict(list)
        for c, sups in superclasses.items():
            for s in sups:
                subclasses[s].append(c)
        direct_subs: dict[str, list[str]] = defaultdict(list)
        for c, sups in direct_sup.items():
            for s in sups:
                direct_subs[s].append(c)

        classes.discard(OWL_THING); classes.discard(OWL_NOTHING)
        return ClassificationResult(
            version_id=version_id,
            classified_at=datetime.now(timezone.utc).isoformat(),
            class_count=len(classes),
            superclasses=dict(superclasses),
            subclasses=dict(subclasses),
            direct_superclasses={k: sorted(v) for k, v in direct_sup.items()},
            direct_subclasses=dict(direct_subs),
            unsatisfiable=unsatisfiable,
            proof_traces={},
            duration_ms=round((time.monotonic() - t0) * 1000, 1),
        )
```

Remove the dead `for s, _, o in store.quads_for_pattern(...) and []` scaffold line if the implementer's editor flags it — it is a no-op left only to make the asserted-edge collection order obvious; the real collection is the `RDFS_SUB_NN` loop below it. (Clean it up: delete the `for ... and []: pass` block.)

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd docker/reasoner-service && python -m pytest test_konclude_backend.py -q`
Expected: PASS (1 passed) when the binary is present. If py-horned-owl's serialisation keyword differs (`save_to_string(serialization=...)`), fix per the actual py-horned-owl 1.4 API and re-run.

- [ ] **Step 5: Commit**

```bash
cd ~/code/ontoexplorer
git add docker/reasoner-service/konclude_backend.py docker/reasoner-service/test_konclude_backend.py
git -c user.email=michel.dumontier@gmail.com commit -m "feat(reasoner-service): Konclude classification backend (subprocess)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Reasoner-aware HTTP contract

Wire the registry into `main.py`: `reasoner` field on requests, cache routing, `GET /reasoners`, justify routing with 422 + `format`.

**Files:**
- Modify: `docker/reasoner-service/main.py`
- Test: `docker/reasoner-service/test_reasoners_endpoint.py`

**Interfaces:**
- Consumes: `registry.get_backend`, `registry.list_reasoners`, `registry.default_reasoner`; the reasoner-scoped `cache.py` functions from Task 2.
- Produces: HTTP endpoints — `GET /reasoners`, `POST /classify` (now with `reasoner`), `POST /classify/{vid}/justification` (with `reasoner`, `format`).

- [ ] **Step 1: Write the failing test**

Create `docker/reasoner-service/test_reasoners_endpoint.py`:

```python
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import fakeredis
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch):
    import cache as cache_mod
    monkeypatch.setattr(cache_mod, "_redis", fakeredis.FakeStrictRedis())


@pytest.fixture
def client():
    import main
    return TestClient(main.app)


def test_reasoners_endpoint_lists_capabilities(client):
    resp = client.get("/reasoners")
    assert resp.status_code == 200
    by_name = {r["name"]: r for r in resp.json()}
    assert {"whelk", "rdflib", "rustdl", "konclude"} <= set(by_name)
    assert "justify" in by_name["rustdl"]["capabilities"]
    assert "justify" not in by_name["konclude"]["capabilities"]
    assert "profile" in by_name["whelk"] and "available" in by_name["whelk"]


def test_justification_422_for_konclude(client, monkeypatch):
    # A cached classification must exist for the endpoint to proceed to the
    # capability check; store a minimal one under the konclude key.
    import cache as cache_mod
    from classifier import ClassificationResult
    r = ClassificationResult("v1", "t", 0, {}, {}, {}, {}, [], {}, 1.0)
    cache_mod.store_classification(r, "konclude")
    resp = client.post("/classify/v1/justification",
                       json={"sub": "s", "sup": "o", "reasoner": "konclude"})
    assert resp.status_code == 422
    assert "does not support justifications" in resp.json()["detail"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd docker/reasoner-service && python -m pytest test_reasoners_endpoint.py -q`
Expected: FAIL (`/reasoners` 404; justification endpoint lacks `reasoner`/422 handling). Install test deps if needed: `pip install httpx fakeredis`.

- [ ] **Step 3: Add reasoner to request models + GET /reasoners**

In `main.py`, extend the request models and add the endpoint. Add `reasoner` to `ClassifyRequest` and `JustificationRequest`:

```python
from registry import get_backend, list_reasoners, default_reasoner


class ClassifyRequest(BaseModel):
    ntriples: str
    version_id: str
    reasoner: str | None = None


class JustificationRequest(BaseModel):
    sub: str
    sup: str | None = None
    type: str | None = None
    max_justifications: int = 1
    reasoner: str | None = None


@app.get("/reasoners")
def get_reasoners():
    from dataclasses import asdict
    return [
        {**asdict(info), "capabilities": sorted(info.capabilities)}
        for info in list_reasoners()
    ]
```

- [ ] **Step 4: Route /classify through the registry with reasoner-scoped cache**

In `run_classify` and its `_run` worker, resolve `reasoner = req.reasoner or default_reasoner()`, call `get_backend(reasoner).classify_ntriples(req.ntriples, req.version_id)`, and thread `reasoner` through every `cache.*` call. Update `_load_or_404`, `get_classification`, the subclass/superclass/consistency GETs to accept a `reasoner` query param (default `default_reasoner()`) and pass it to `load_classification`. Reject unknown reasoners:

```python
@app.post("/classify", status_code=202)
def run_classify(req: ClassifyRequest):
    reasoner = req.reasoner or default_reasoner()
    try:
        backend = get_backend(reasoner)
    except KeyError:
        raise HTTPException(422, f"unknown reasoner '{reasoner}'")

    if load_classification(req.version_id, reasoner) is not None:
        return {"version_id": req.version_id, "reasoner": reasoner, "status": "done"}
    if (req.version_id, reasoner) in _in_progress:
        return {"version_id": req.version_id, "reasoner": reasoner, "status": "running"}
    _in_progress.add((req.version_id, reasoner))

    def _run(version_id: str) -> None:
        try:
            result = backend.classify_ntriples(req.ntriples, version_id)
            store_input_axioms(version_id, req.ntriples, reasoner)
            store_classification(result, reasoner)
        except Exception as exc:
            log.exception("classify_background_error")
            store_classification_error(version_id, f"{type(exc).__name__}: {exc}"[:1000], reasoner)
        finally:
            _in_progress.discard((version_id, reasoner))

    _classifier_pool.submit(_run, req.version_id)
    return {"version_id": req.version_id, "reasoner": reasoner, "status": "running"}
```

Change `_in_progress` to hold `(version_id, reasoner)` tuples (declared as `set[tuple[str, str]]`). Update `_load_or_404(version_id, reasoner)` and every classification GET to take and pass `reasoner: str = Query(default_reasoner())` (import `Query` from fastapi). Update the cache import line to the Task-2 signatures.

- [ ] **Step 5: Route justification through the backend with capability check + format**

Rewrite `compute_justification_endpoint`:

```python
@app.post("/classify/{version_id}/justification")
def compute_justification_endpoint(version_id: str, req: JustificationRequest):
    import time
    reasoner = req.reasoner or default_reasoner()
    try:
        backend = get_backend(reasoner)
    except KeyError:
        raise HTTPException(422, f"unknown reasoner '{reasoner}'")
    if "justify" not in backend.info.capabilities:
        raise HTTPException(422, f"reasoner '{reasoner}' does not support justifications")

    _load_or_404(version_id, reasoner)  # ensure classification exists
    sup = req.sup if req.sup else str(rdflib.OWL.Nothing)

    cached = load_justification(version_id, req.sub, sup, req.max_justifications, reasoner)
    if cached:
        return cached

    ntriples = load_input_axioms(version_id, reasoner) or ""
    t0 = time.monotonic()
    try:
        sets, fmt = backend.justify(ntriples, req.sub, sup, req.max_justifications)
    except Exception:
        sets, fmt = [], "ntriples"
        log.exception("justification_compute_failed")

    response = {
        "version_id": version_id, "reasoner": reasoner,
        "sub": req.sub, "sup": sup, "format": fmt,
        "justifications_requested": req.max_justifications,
        "justifications_found": len(sets),
        "minimal": True, "timed_out": False,
        "justifications": sets, "proof_traces": [],
        "duration_ms": round((time.monotonic() - t0) * 1000, 1),
    }
    store_justification(version_id, req.sub, sup, req.max_justifications, reasoner, response)
    return response
```

Update the `cache` import at the top of `main.py` to match Task-2 signatures, and remove now-dead helpers (`_reconstruct_graph_from_traces`, `_load_input_graph`) only if nothing else references them — otherwise leave them.

- [ ] **Step 6: Run the test to verify it passes**

Run: `cd docker/reasoner-service && python -m pytest test_reasoners_endpoint.py -q`
Expected: PASS (2 passed).

- [ ] **Step 7: Run the whole service test suite (no regressions)**

Run: `cd docker/reasoner-service && python -m pytest -q`
Expected: PASS or SKIP for every test (rustdl/konclude/whelk tests skip when their engine is absent; no failures).

- [ ] **Step 8: Commit**

```bash
cd ~/code/ontoexplorer
git add docker/reasoner-service/main.py docker/reasoner-service/test_reasoners_endpoint.py
git -c user.email=michel.dumontier@gmail.com commit -m "feat(reasoner-service): reasoner-aware HTTP contract + GET /reasoners

reasoner field on /classify & /justification, reasoner-scoped cache routing,
422 for no-justify reasoners, format field on justification response.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Package rustdl + Konclude into the image

Extend the (amd64) Dockerfile so the built image ships rustdl and Konclude, and verify all four reasoners report `available: true` from a running container.

**Files:**
- Modify: `docker/reasoner-service/Dockerfile`

**Interfaces:**
- Consumes: the source files created in Tasks 2–7 (already `COPY`ed if listed).
- Produces: a runnable image where `GET /reasoners` shows `available: true` for whelk, rdflib, rustdl, konclude.

- [ ] **Step 1: Confirm the Konclude binary path inside the image**

Run:
```bash
docker run --rm konclude/konclude:latest which Konclude 2>/dev/null || \
docker run --rm --entrypoint sh konclude/konclude:latest -c 'ls -1 /Konclude* 2>/dev/null; find / -name Konclude -type f 2>/dev/null | head'
```
Record the absolute path printed (referred to below as `<KON_PATH>`). Note the image tag actually available (`konclude/konclude:latest` or a pinned version).

- [ ] **Step 2: Add builder stages + installs to the Dockerfile**

Edit `docker/reasoner-service/Dockerfile` to a multi-stage build. Keep the existing pip install block; add rustdl and Konclude:

```dockerfile
# --- rustdl builder: build the owl-dl-py wheel from source ---
FROM rust:1-slim AS rustdl-builder
RUN apt-get update && apt-get install -y --no-install-recommends git python3 python3-pip \
 && pip install --break-system-packages maturin
ARG RUSTDL_REF=main
RUN git clone --depth 1 --branch ${RUSTDL_REF} https://github.com/MaastrichtU-IDS/rustdl /src
WORKDIR /src
RUN maturin build --release -m crates/owl-dl-py/Cargo.toml --out /wheels

# --- Konclude binary source ---
FROM konclude/konclude:latest AS konclude-src

# --- final image ---
FROM python:3.12-slim
WORKDIR /app
# (existing pip install block stays here, unchanged)
COPY wheels/ /tmp/wheels/
RUN pip install --no-cache-dir \
    "fastapi==0.111.*" "uvicorn[standard]" "rdflib" "redis>=5.0" "requests>=2.31" \
    "py-horned-owl==1.4.*" /tmp/wheels/py_whelk-*.whl "pyoxigraph>=0.4" \
 && rm -rf /tmp/wheels

# rustdl wheel
COPY --from=rustdl-builder /wheels/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm -rf /tmp/*.whl

# Konclude binary (path from Step 1)
COPY --from=konclude-src <KON_PATH> /usr/local/bin/Konclude
RUN chmod +x /usr/local/bin/Konclude
# Konclude needs libtbb at runtime:
RUN apt-get update && apt-get install -y --no-install-recommends libtbb12 \
 && rm -rf /var/lib/apt/lists/*

COPY main.py classifier.py whelk_classifier.py cache.py justification.py \
     registry.py rustdl_backend.py konclude_backend.py ./

EXPOSE 8001
HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/health')"
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
```

Replace `<KON_PATH>` with the path from Step 1. If `libtbb12` is the wrong package name for the base, adjust to `libtbb2` (Debian bookworm ships `libtbb12`). Pin `RUSTDL_REF` to a known-good tag once one exists; `main` is acceptable for SP1.

- [ ] **Step 3: Build the image**

Run: `cd ~/code/ontoexplorer && docker compose build reasoner-service 2>&1 | tail -20`
Expected: build succeeds. (First build is slow — the Rust stage compiles rustdl.)

- [ ] **Step 4: Verify all reasoners are available at runtime**

Run:
```bash
cd ~/code/ontoexplorer && docker compose up -d reasoner-service && sleep 8
curl -s http://localhost:8001/reasoners | python3 -m json.tool
```
Expected: JSON array where whelk, rdflib, rustdl, konclude each show `"available": true`. If rustdl or konclude show `false`, the import/binary isn't resolving — fix the wheel install or `COPY` path and rebuild.

- [ ] **Step 5: Smoke-test classification through each new reasoner**

Run:
```bash
NT='<http://example.org/A> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://www.w3.org/2002/07/owl#Class> .
<http://example.org/B> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://www.w3.org/2002/07/owl#Class> .
<http://example.org/C> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://www.w3.org/2002/07/owl#Class> .
<http://example.org/A> <http://www.w3.org/2000/01/rdf-schema#subClassOf> <http://example.org/B> .
<http://example.org/B> <http://www.w3.org/2000/01/rdf-schema#subClassOf> <http://example.org/C> .'
for R in rustdl konclude; do
  curl -s -X POST http://localhost:8001/classify -H 'Content-Type: application/json' \
    -d "$(python3 -c 'import json,sys,os; print(json.dumps({"ntriples":os.environ["NT"],"version_id":"vtest-"+sys.argv[1],"reasoner":sys.argv[1]}))' $R)"
  sleep 3
  echo "  $R superclasses:"; curl -s "http://localhost:8001/classify/vtest-$R?reasoner=$R" | python3 -c 'import sys,json;print(json.load(sys.stdin)["superclasses"])'
done
```
Expected: each prints `{'http://example.org/A': ['http://example.org/C']}` (order aside).

- [ ] **Step 6: Commit**

```bash
cd ~/code/ontoexplorer
git add docker/reasoner-service/Dockerfile
git -c user.email=michel.dumontier@gmail.com commit -m "build(reasoner-service): bundle rustdl wheel + Konclude binary

Multi-stage build: maturin-built owl-dl-py wheel and the prebuilt Konclude
binary (emulated on arm64). All four reasoners available at runtime.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage** (each spec requirement → task):
- Rename elk-service → reasoner-service → Task 1. ✓
- Capability-aware registry → Task 3. ✓
- rustdl classify (binding) → Task 4. ✓
- rustdl justify (native, Manchester, `format` field) → Task 5 + Task 7. ✓
- Konclude classify/consistency (CLI, prebuilt) → Task 6 + Task 8. ✓
- Reasoner on `/classify`, reasoner-scoped cache key → Task 2 + Task 7. ✓
- `GET /reasoners` (name/profile/capabilities/available) → Task 7. ✓
- 422 on justify for no-justify reasoner → Task 7. ✓
- Backward-compatible (omit reasoner ⇒ default) → Task 7 (`req.reasoner or default_reasoner()`), Task 1 (env aliases). ✓
- Packaging (amd64, rustdl maturin, Konclude bundled, libtbb) → Task 8. ✓
- Testing (per-backend + registry + contract) → Tasks 2–7 tests. ✓

**Placeholder scan:** No TBD/TODO. Two spots require a real-environment lookup rather than a guess and say so explicitly: the Konclude binary path (Task 8 Step 1 gives the discovery command) and the exact py-horned-owl `save_to_string` serialisation keyword (Task 6 flags confirming against the 1.4 API). These are discovery steps, not placeholders.

**Type consistency:** `Backend.classify_ntriples(ntriples, version_id) -> ClassificationResult` and `Backend.justify(ntriples, sub, sup, max_justifications) -> (list[list[str]], str)` are used identically in Tasks 3–7. Cache signatures defined in Task 2 match every call site in Task 7. `_in_progress` is consistently a `set[tuple[str, str]]` after Task 7. Reasoner names are the same four lowercase strings throughout.

**Known cross-task cleanup:** Task 6 Step 3 leaves a deliberately-marked dead scaffold line the implementer must delete (called out in-step). The whelk `justify` adapter (Task 3) depends on `compute_justifications` accepting an empty `ClassificationResult`; if that assumption fails during Task 3 Step 5, use the input-axioms path exactly as `main.py` did before this change.
