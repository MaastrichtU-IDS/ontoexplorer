# MOD-API Compatibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose OntoExplorer as a MOD-API-compliant semantic artefact catalogue at `/mod/` serving JSON-LD, Turtle, RDF/XML, and HTML with rate limiting.

**Architecture:** A new `ontoexplorer/modules/mod/` package provides `context.py` (JSON-LD @context), `response.py` (RDFResponse content negotiation), `ratelimit.py` (Redis-backed rate limiter), and `builder.py` (pure functions that build `rdflib.Graph` objects from DB rows). A new `ontoexplorer/api/mod.py` router wires all 30 read-only endpoints. No new DB tables — reads from `ontologies`, `versions`, `ontology_meta_profiles`, and Redis stats cache.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, rdflib (already in dependencies), Jinja2 (new dep), Redis (sync via `asyncio.to_thread`), pyoxigraph (for resources queries), pytest + fakeredis.

---

## Codebase orientation

Before starting, understand these existing patterns:

- **Config**: `ontoexplorer/config.py` — `pydantic-settings` class, reads from `.env`. Add fields with defaults.
- **DB models**: `ontoexplorer/models/db.py` — `Ontology`, `OntologyVersion`, `OntologyMetaProfile`. The `OntologyMetaProfile.resolved` dict holds keys: `title`, `description`, `creator`, `contributor`, `publisher`, `license`, `homepage`, `version_info`, `prefix`, `namespace_uri`, `language`, `citation`, `funding`.
- **Stats cache**: Redis key `version_stats:{version_id}` → JSON with `class_count`, `property_count`, `individual_count`, `triple_count` (all strings).
- **Oxigraph queries**: `from ontoexplorer.clients.oxigraph import get_store, graph_iri` → `store.query(sparql)` wrapped in `asyncio.to_thread`.
- **Auth**: `from ontoexplorer.modules.auth.dependencies import get_current_user` → returns `User | None`, never raises.
- **Tests**: `tests/integration/` uses `@pytest.mark.anyio` with `client` fixture (httpx AsyncClient). `fakeredis` is a dev dependency.
- **Router registration**: `ontoexplorer/main.py` calls `app.include_router(...)` — add `mod_router` at prefix `/mod`.

---

## File map

| File | Action |
|---|---|
| `pyproject.toml` | Modify — add `jinja2` to dependencies |
| `ontoexplorer/config.py` | Modify — add 4 MOD config vars |
| `.env.example` | Modify — document new MOD vars |
| `docs/mod-metadata-elements.md` | Create — reference field list for metadata editor |
| `ontoexplorer/modules/mod/__init__.py` | Create (empty) |
| `ontoexplorer/modules/mod/context.py` | Create — `MOD_CONTEXT` dict |
| `ontoexplorer/modules/mod/response.py` | Create — `RDFResponse` class |
| `ontoexplorer/modules/mod/ratelimit.py` | Create — `mod_rate_limit` dependency |
| `ontoexplorer/modules/mod/builder.py` | Create — all graph builder functions |
| `ontoexplorer/api/mod.py` | Create — 30-endpoint router |
| `ontoexplorer/main.py` | Modify — register `mod_router` |
| `tests/integration/test_mod_api.py` | Create — integration tests |

---

## Task 1: Config + dependencies + metadata reference doc

**Files:**
- Modify: `pyproject.toml`
- Modify: `ontoexplorer/config.py`
- Modify: `.env.example`
- Create: `docs/mod-metadata-elements.md`

- [ ] **Step 1: Add jinja2 to pyproject.toml**

In `pyproject.toml`, add `"jinja2"` to the `dependencies` array (after `"anthropic>=0.97"`):

```toml
dependencies = [
    "fastapi>=0.111",
    "uvicorn[standard]",
    "celery[redis]",
    "sqlalchemy[asyncio]>=2.0",
    "asyncpg",
    "alembic",
    "pydantic-settings>=2.0",
    "py_horned_owl",
    "rdflib",
    "pyoxigraph",
    "minio",
    "httpx",
    "authlib",
    "python-jose[cryptography]",
    "prometheus-fastapi-instrumentator",
    "python-multipart",
    "structlog>=24.0",
    "prometheus-client",
    "lark>=1.2",
    "redis>=6.0",
    "fastembed>=0.3",
    "pgvector>=0.3",
    "anthropic>=0.97",
    "jinja2",
]
```

- [ ] **Step 2: Add MOD config vars to config.py**

In `ontoexplorer/config.py`, add these four fields to the `Settings` class (after `admin_emails`):

```python
    # MOD-API
    mod_catalogue_title: str = "OntoExplorer Catalogue"
    mod_catalogue_description: str = "A FAIR ontology repository"
    mod_rate_limit_anon: int = 1000
    mod_rate_limit_auth: int = 10000
```

- [ ] **Step 3: Add MOD vars to .env.example**

Append to `.env.example`:

```
# ── MOD-API ───────────────────────────────────────────────────────────────────
MOD_CATALOGUE_TITLE=OntoExplorer Catalogue
MOD_CATALOGUE_DESCRIPTION=A FAIR ontology repository
# Rate limits for /mod/* endpoints (requests per day)
MOD_RATE_LIMIT_ANON=1000
MOD_RATE_LIMIT_AUTH=10000
```

- [ ] **Step 4: Sync dependencies**

```bash
cd /path/to/ontoexplorer && uv sync
```

Expected: resolves jinja2, no errors.

- [ ] **Step 5: Create docs/mod-metadata-elements.md**

```markdown
# MOD Metadata Elements Reference

All fields from `modSemanticArtefact` (MOD-API OpenAPI spec). Used as a shopping list
for the OntoExplorer ontology metadata editor.

## Tiers

- **Captured** — already stored and exposed by OntoExplorer
- **Derivable** — computable from existing data, not yet exposed
- **Missing** — needs new UI in the Profile/metadata editor

---

## Core Identity

| MOD Property | URI | Tier | OntoExplorer Source |
|---|---|---|---|
| `@id` | (ontology IRI) | Captured | `ontology.iri` |
| `mod:acronym` | `https://w3id.org/mod#acronym` | Captured | `ontology.shortname` |
| `dcterms:title` | `http://purl.org/dc/terms/title` | Captured | `meta_profile.resolved["title"]` |
| `dcterms:description` | `http://purl.org/dc/terms/description` | Captured | `meta_profile.resolved["description"]` |

## Provenance & Attribution

| MOD Property | URI | Tier | OntoExplorer Source |
|---|---|---|---|
| `dcterms:creator` | `http://purl.org/dc/terms/creator` | Captured | `meta_profile.resolved["creator"]` |
| `dcterms:contributor` | `http://purl.org/dc/terms/contributor` | Captured | `meta_profile.resolved["contributor"]` |
| `dcterms:publisher` | `http://purl.org/dc/terms/publisher` | Captured | `meta_profile.resolved["publisher"]` |
| `schema:funding` | `https://schema.org/funding` | Captured | `meta_profile.resolved["funding"]` |
| `prov:wasGeneratedBy` | `http://www.w3.org/ns/prov#wasGeneratedBy` | Missing | — |

## Rights & Access

| MOD Property | URI | Tier | OntoExplorer Source |
|---|---|---|---|
| `dcterms:license` | `http://purl.org/dc/terms/license` | Captured | `meta_profile.resolved["license"]` |
| `dcterms:rights` | `http://purl.org/dc/terms/rights` | Missing | — |
| `dcterms:accessRights` | `http://purl.org/dc/terms/accessRights` | Missing | — |

## Discovery & Navigation

| MOD Property | URI | Tier | OntoExplorer Source |
|---|---|---|---|
| `foaf:homepage` | `http://xmlns.com/foaf/0.1/homepage` | Captured | `meta_profile.resolved["homepage"]` |
| `dcterms:language` | `http://purl.org/dc/terms/language` | Captured | `meta_profile.resolved["language"]` |
| `dcat:keyword` | `http://www.w3.org/ns/dcat#keyword` | Missing | — |
| `dcat:theme` | `http://www.w3.org/ns/dcat#theme` | Missing | — |
| `dcat:landingPage` | `http://www.w3.org/ns/dcat#landingPage` | Missing | — |

## Versioning

| MOD Property | URI | Tier | OntoExplorer Source |
|---|---|---|---|
| `owl:versionInfo` | `http://www.w3.org/2002/07/owl#versionInfo` | Captured | `meta_profile.resolved["version_info"]` |
| `owl:versionIRI` | `http://www.w3.org/2002/07/owl#versionIRI` | Captured | `version.version_iri` |
| `dcterms:created` | `http://purl.org/dc/terms/created` | Captured | `ontology.created_at` |
| `dcterms:modified` | `http://purl.org/dc/terms/modified` | Captured | `version.created_at` |
| `owl:priorVersion` | `http://www.w3.org/2002/07/owl#priorVersion` | Derivable | previous `version.version_iri` |
| `owl:backwardCompatibleWith` | `http://www.w3.org/2002/07/owl#backwardCompatibleWith` | Missing | — |
| `owl:incompatibleWith` | `http://www.w3.org/2002/07/owl#incompatibleWith` | Missing | — |

## Technical Metadata

| MOD Property | URI | Tier | OntoExplorer Source |
|---|---|---|---|
| `vann:preferredNamespacePrefix` | `http://purl.org/vocab/vann/preferredNamespacePrefix` | Captured | `meta_profile.resolved["prefix"]` |
| `vann:preferredNamespaceUri` | `http://purl.org/vocab/vann/preferredNamespaceUri` | Captured | `meta_profile.resolved["namespace_uri"]` |
| `mod:numberOfClasses` | `https://w3id.org/mod#numberOfClasses` | Derivable | Redis stats `class_count` |
| `mod:numberOfProperties` | `https://w3id.org/mod#numberOfProperties` | Derivable | Redis stats `property_count` |
| `mod:numberOfIndividuals` | `https://w3id.org/mod#numberOfIndividuals` | Derivable | Redis stats `individual_count` |
| `void:triples` | `http://rdfs.org/ns/void#triples` | Derivable | Redis stats `triple_count` |
| `mod:status` | `https://w3id.org/mod#status` | Derivable | `version.status` → MOD URI |

## Citation & Scholarly Use

| MOD Property | URI | Tier | OntoExplorer Source |
|---|---|---|---|
| `schema:citation` | `https://schema.org/citation` | Captured | `meta_profile.resolved["citation"]` |
| `dcterms:bibliographicCitation` | `http://purl.org/dc/terms/bibliographicCitation` | Missing | — |
| `mod:knownUsage` | `https://w3id.org/mod#knownUsage` | Missing | — |
| `mod:usedInProject` | `https://w3id.org/mod#usedInProject` | Missing | — |

## Semantic Relations (Missing — needs metadata editor)

| MOD Property | URI | Tier | Notes |
|---|---|---|---|
| `mod:competencyQuestion` | `https://w3id.org/mod#competencyQuestion` | Missing | Scope/purpose statement |
| `mod:endorsedBy` | `https://w3id.org/mod#endorsedBy` | Missing | Endorsing organization |
| `mod:reliesOn` | `https://w3id.org/mod#reliesOn` | Missing | External ontologies used |
| `mod:similar` | `https://w3id.org/mod#similar` | Missing | Related ontologies |
| `mod:generalizes` | `https://w3id.org/mod#generalizes` | Missing | More general ontology |
| `mod:specializes` | `https://w3id.org/mod#specializes` | Missing | More specific ontology |
| `mod:hasDisjunctionsWith` | `https://w3id.org/mod#hasDisjunctionsWith` | Missing | Disjoint ontology |
| `mod:hasEquivalences` | `https://w3id.org/mod#hasEquivalences` | Missing | Equivalent ontology |
```

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml ontoexplorer/config.py .env.example docs/mod-metadata-elements.md
git commit -m "feat(mod): add config, jinja2 dep, and metadata elements reference"
```

---

## Task 2: Module scaffold + JSON-LD context

**Files:**
- Create: `ontoexplorer/modules/mod/__init__.py`
- Create: `ontoexplorer/modules/mod/context.py`
- Create: `tests/unit/test_mod_context.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_mod_context.py
from ontoexplorer.modules.mod.context import MOD_CONTEXT


def test_context_has_required_prefixes():
    ctx = MOD_CONTEXT["@context"]
    for prefix in ["dcterms", "dcat", "mod", "owl", "foaf", "skos", "void", "rdf", "rdfs", "xsd", "vann", "schema", "hydra", "sd"]:
        assert prefix in ctx, f"Missing prefix: {prefix}"


def test_mod_namespace():
    assert MOD_CONTEXT["@context"]["mod"] == "https://w3id.org/mod#"


def test_dcat_namespace():
    assert MOD_CONTEXT["@context"]["dcat"] == "http://www.w3.org/ns/dcat#"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /path/to/ontoexplorer && uv run pytest tests/unit/test_mod_context.py -v
```

Expected: `ModuleNotFoundError: No module named 'ontoexplorer.modules.mod'`

- [ ] **Step 3: Create module scaffold and context**

```python
# ontoexplorer/modules/mod/__init__.py
```

```python
# ontoexplorer/modules/mod/context.py
MOD_CONTEXT: dict = {
    "@context": {
        "dcterms": "http://purl.org/dc/terms/",
        "dcat": "http://www.w3.org/ns/dcat#",
        "mod": "https://w3id.org/mod#",
        "owl": "http://www.w3.org/2002/07/owl#",
        "foaf": "http://xmlns.com/foaf/0.1/",
        "skos": "http://www.w3.org/2004/02/skos/core#",
        "void": "http://rdfs.org/ns/void#",
        "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
        "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
        "xsd": "http://www.w3.org/2001/XMLSchema#",
        "vann": "http://purl.org/vocab/vann/",
        "schema": "https://schema.org/",
        "hydra": "http://www.w3.org/ns/hydra/core#",
        "sd": "http://www.w3.org/ns/sparql-service-description#",
        "prov": "http://www.w3.org/ns/prov#",
    }
}
```

- [ ] **Step 4: Run tests to confirm pass**

```bash
cd /path/to/ontoexplorer && uv run pytest tests/unit/test_mod_context.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/modules/mod/__init__.py ontoexplorer/modules/mod/context.py tests/unit/test_mod_context.py
git commit -m "feat(mod): add module scaffold and JSON-LD context"
```

---

## Task 3: RDFResponse class

**Files:**
- Create: `ontoexplorer/modules/mod/response.py`
- Create: `tests/unit/test_mod_response.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_mod_response.py
import json
import pytest
from rdflib import Graph, URIRef, Literal
from rdflib.namespace import DCTERMS

from ontoexplorer.modules.mod.response import RDFResponse, _negotiate_format


def _sample_graph() -> Graph:
    g = Graph()
    g.add((URIRef("http://example.org/ont"), DCTERMS.title, Literal("Test Ontology")))
    return g


def test_negotiate_format_param_jsonld():
    assert _negotiate_format("jsonld", None) == "jsonld"


def test_negotiate_format_param_ttl():
    assert _negotiate_format("ttl", None) == "turtle"


def test_negotiate_format_param_rdfxml():
    assert _negotiate_format("rdfxml", None) == "xml"


def test_negotiate_format_param_html():
    assert _negotiate_format("html", None) == "html"


def test_negotiate_format_accept_turtle():
    assert _negotiate_format(None, "text/turtle, */*;q=0.8") == "turtle"


def test_negotiate_format_accept_rdfxml():
    assert _negotiate_format(None, "application/rdf+xml") == "xml"


def test_negotiate_format_accept_html():
    assert _negotiate_format(None, "text/html") == "html"


def test_negotiate_format_default():
    assert _negotiate_format(None, None) == "jsonld"
    assert _negotiate_format(None, "application/json") == "jsonld"


def test_rdf_response_jsonld():
    g = _sample_graph()
    resp = RDFResponse(g, format_param="jsonld")
    assert resp.media_type.startswith("application/ld+json")
    data = json.loads(resp.body)
    assert "@context" in data


def test_rdf_response_turtle():
    g = _sample_graph()
    resp = RDFResponse(g, format_param="ttl")
    assert resp.media_type.startswith("text/turtle")
    assert b"Test Ontology" in resp.body


def test_rdf_response_rdfxml():
    g = _sample_graph()
    resp = RDFResponse(g, format_param="rdfxml")
    assert resp.media_type.startswith("application/rdf+xml")
    assert b"Test Ontology" in resp.body


def test_rdf_response_html():
    g = _sample_graph()
    resp = RDFResponse(g, format_param="html")
    assert resp.media_type.startswith("text/html")
    assert b"Test Ontology" in resp.body
    assert b"<table" in resp.body


def test_rdf_response_jsonld_has_graph_key_for_list():
    g = _sample_graph()
    resp = RDFResponse(g, format_param="jsonld")
    data = json.loads(resp.body)
    # Either @graph (list) or inline triples — must have @context
    assert "@context" in data
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /path/to/ontoexplorer && uv run pytest tests/unit/test_mod_response.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Create response.py**

```python
# ontoexplorer/modules/mod/response.py
import json

from fastapi import Response
from rdflib import Graph


HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>{{ title }}</title>
<style>
body{font-family:sans-serif;max-width:960px;margin:2rem auto;padding:0 1rem;color:#222}
h1{font-size:1.4rem;margin-bottom:1rem}
table{border-collapse:collapse;width:100%}
th,td{border:1px solid #ddd;padding:6px 10px;text-align:left;vertical-align:top;font-size:.85rem}
th{background:#f5f5f5;font-weight:600}
td:first-child{white-space:nowrap;color:#555}
a{color:#0066cc;text-decoration:none}
a:hover{text-decoration:underline}
</style>
</head>
<body>
<h1>{{ title }}</h1>
<table>
<thead><tr><th>Property</th><th>Value</th></tr></thead>
<tbody>
{% for pred, obj in rows %}
<tr>
  <td><a href="{{ pred }}">{{ pred_label(pred) }}</a></td>
  <td>{% if obj.startswith("http") %}<a href="{{ obj }}">{{ obj }}</a>{% else %}{{ obj }}{% endif %}</td>
</tr>
{% endfor %}
</tbody>
</table>
</body>
</html>"""


def _negotiate_format(fmt_param: str | None, accept: str | None) -> str:
    FORMAT_MAP = {"jsonld": "jsonld", "ttl": "turtle", "rdfxml": "xml", "html": "html"}
    if fmt_param and fmt_param in FORMAT_MAP:
        return FORMAT_MAP[fmt_param]
    if accept:
        if "text/turtle" in accept:
            return "turtle"
        if "application/rdf+xml" in accept:
            return "xml"
        if "text/html" in accept:
            return "html"
    return "jsonld"


def _render_html(graph: Graph) -> str:
    from jinja2 import Environment
    env = Environment(autoescape=True)

    def pred_label(uri: str) -> str:
        if "#" in uri:
            return uri.split("#")[-1]
        return uri.rstrip("/").split("/")[-1]

    env.globals["pred_label"] = pred_label

    title_pred = "http://purl.org/dc/terms/title"
    title = next(
        (str(o) for _, p, o in graph if str(p) == title_pred),
        "RDF Graph",
    )
    rows = sorted((str(p), str(o)) for _, p, o in graph)
    tmpl = env.from_string(HTML_TEMPLATE)
    return tmpl.render(title=title, rows=rows)


def _serialize(graph: Graph, fmt: str) -> tuple[bytes, str]:
    if fmt == "turtle":
        return graph.serialize(format="turtle").encode("utf-8"), "text/turtle; charset=utf-8"
    if fmt == "xml":
        return graph.serialize(format="xml").encode("utf-8"), "application/rdf+xml; charset=utf-8"
    if fmt == "html":
        return _render_html(graph).encode("utf-8"), "text/html; charset=utf-8"
    # JSON-LD
    from ontoexplorer.modules.mod.context import MOD_CONTEXT
    raw = json.loads(graph.serialize(format="json-ld"))
    if isinstance(raw, list):
        data: dict = {"@context": MOD_CONTEXT["@context"], "@graph": raw}
    else:
        data = {"@context": MOD_CONTEXT["@context"], **raw}
    return json.dumps(data, indent=2).encode("utf-8"), "application/ld+json; charset=utf-8"


class RDFResponse(Response):
    def __init__(
        self,
        graph: Graph,
        *,
        format_param: str | None = None,
        accept: str | None = None,
    ) -> None:
        fmt = _negotiate_format(format_param, accept)
        content, media_type = _serialize(graph, fmt)
        super().__init__(content=content, media_type=media_type)
```

- [ ] **Step 4: Run tests to confirm pass**

```bash
cd /path/to/ontoexplorer && uv run pytest tests/unit/test_mod_response.py -v
```

Expected: all 13 tests pass.

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/modules/mod/response.py tests/unit/test_mod_response.py
git commit -m "feat(mod): add RDFResponse with JSON-LD/Turtle/RDF-XML/HTML content negotiation"
```

---

## Task 4: Rate limiting dependency

**Files:**
- Create: `ontoexplorer/modules/mod/ratelimit.py`
- Create: `tests/unit/test_mod_ratelimit.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_mod_ratelimit.py
import pytest
import fakeredis
from unittest.mock import MagicMock, patch
from fastapi import HTTPException

from ontoexplorer.modules.mod.ratelimit import mod_rate_limit


def _fake_request(ip: str = "1.2.3.4") -> MagicMock:
    req = MagicMock()
    req.client.host = ip
    return req


def _fake_settings(anon_limit: int = 1000, auth_limit: int = 10000) -> MagicMock:
    s = MagicMock()
    s.mod_rate_limit_anon = anon_limit
    s.mod_rate_limit_auth = auth_limit
    return s


@pytest.mark.anyio
async def test_anon_request_allowed():
    fr = fakeredis.FakeRedis(decode_responses=True)
    with patch("ontoexplorer.modules.mod.ratelimit._get_redis", return_value=fr), \
         patch("ontoexplorer.modules.mod.ratelimit.get_settings", return_value=_fake_settings()):
        await mod_rate_limit(request=_fake_request(), user=None)  # no exception


@pytest.mark.anyio
async def test_anon_rate_limit_exceeded():
    fr = fakeredis.FakeRedis(decode_responses=True)
    with patch("ontoexplorer.modules.mod.ratelimit._get_redis", return_value=fr), \
         patch("ontoexplorer.modules.mod.ratelimit.get_settings", return_value=_fake_settings(anon_limit=2)):
        req = _fake_request()
        await mod_rate_limit(request=req, user=None)
        await mod_rate_limit(request=req, user=None)
        with pytest.raises(HTTPException) as exc_info:
            await mod_rate_limit(request=req, user=None)
        assert exc_info.value.status_code == 429
        assert "Retry-After" in exc_info.value.headers


@pytest.mark.anyio
async def test_authenticated_uses_higher_limit():
    fr = fakeredis.FakeRedis(decode_responses=True)
    fake_user = MagicMock()
    fake_user.id = "user-123"
    with patch("ontoexplorer.modules.mod.ratelimit._get_redis", return_value=fr), \
         patch("ontoexplorer.modules.mod.ratelimit.get_settings", return_value=_fake_settings(anon_limit=1, auth_limit=5)):
        req = _fake_request()
        # 3 requests — would exceed anon limit of 1, but auth limit is 5
        await mod_rate_limit(request=req, user=fake_user)
        await mod_rate_limit(request=req, user=fake_user)
        await mod_rate_limit(request=req, user=fake_user)  # no exception


@pytest.mark.anyio
async def test_different_ips_have_separate_counters():
    fr = fakeredis.FakeRedis(decode_responses=True)
    with patch("ontoexplorer.modules.mod.ratelimit._get_redis", return_value=fr), \
         patch("ontoexplorer.modules.mod.ratelimit.get_settings", return_value=_fake_settings(anon_limit=1)):
        await mod_rate_limit(request=_fake_request("1.1.1.1"), user=None)
        # Different IP — should not be rate limited
        await mod_rate_limit(request=_fake_request("2.2.2.2"), user=None)  # no exception
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /path/to/ontoexplorer && uv run pytest tests/unit/test_mod_ratelimit.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Create ratelimit.py**

```python
# ontoexplorer/modules/mod/ratelimit.py
import asyncio
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Request, status

from ontoexplorer.config import get_settings
from ontoexplorer.modules.auth.dependencies import get_current_user


def _get_redis():
    from ontoexplorer.modules.search.indexer import _get_redis as _base_get_redis
    return _base_get_redis()


def _increment_and_check(key: str, limit: int) -> int:
    r = _get_redis()
    count = r.incr(key)
    if count == 1:
        now = datetime.now(UTC)
        seconds_until_midnight = (24 * 3600) - (now.hour * 3600 + now.minute * 60 + now.second)
        r.expire(key, max(seconds_until_midnight, 1))
    return count


async def mod_rate_limit(
    request: Request,
    user=Depends(get_current_user),
) -> None:
    settings = get_settings()
    if user is not None:
        key = f"ratelimit:mod:key:{user.id}"
        limit = settings.mod_rate_limit_auth
    else:
        ip = request.client.host if request.client else "unknown"
        key = f"ratelimit:mod:ip:{ip}"
        limit = settings.mod_rate_limit_anon

    count = await asyncio.to_thread(_increment_and_check, key, limit)

    if count > limit:
        now = datetime.now(UTC)
        retry_after = (24 * 3600) - (now.hour * 3600 + now.minute * 60 + now.second)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Use an API key for higher limits.",
            headers={"Retry-After": str(retry_after)},
        )
```

- [ ] **Step 4: Run tests to confirm pass**

```bash
cd /path/to/ontoexplorer && uv run pytest tests/unit/test_mod_ratelimit.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/modules/mod/ratelimit.py tests/unit/test_mod_ratelimit.py
git commit -m "feat(mod): add Redis-backed rate limiting dependency"
```

---

## Task 5: Graph builder — catalogue, artefact, artefacts list

**Files:**
- Create: `ontoexplorer/modules/mod/builder.py`
- Create: `tests/unit/test_mod_builder.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_mod_builder.py
from datetime import datetime, UTC
from types import SimpleNamespace
import pytest
from rdflib import URIRef
from rdflib.namespace import DCTERMS, OWL, RDF

from ontoexplorer.modules.mod.builder import (
    build_catalogue_graph,
    build_artefact_graph,
    build_artefacts_list_graph,
    build_record_graph,
    build_records_list_graph,
    build_distribution_graph,
    build_distributions_list_graph,
    build_resources_summary_graph,
    build_resource_list_graph,
    build_search_results_graph,
    DCAT, MOD, HYDRA,
)


def _ontology(shortname="go", iri="http://purl.obolibrary.org/obo/go.owl", title="Gene Ontology"):
    return SimpleNamespace(
        id="abc1",
        iri=iri,
        shortname=shortname,
        title=title,
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
    )


def _version(ontology_id="abc1", vid="v1", status="ready", format="owl", version_iri=None):
    return SimpleNamespace(
        id=vid,
        ontology_id=ontology_id,
        status=status,
        format=format,
        version_iri=version_iri,
        triple_count=12000,
        created_at=datetime(2024, 6, 1, tzinfo=UTC),
    )


def _meta():
    return {
        "title": "Gene Ontology",
        "description": "A controlled vocabulary for biology",
        "creator": "GO Consortium",
        "license": "https://creativecommons.org/licenses/by/4.0/",
        "version_info": "2024-01-01",
        "prefix": "GO",
        "namespace_uri": "http://purl.obolibrary.org/obo/go/",
    }


def _stats():
    return {"class_count": "5000", "property_count": "20", "individual_count": "0", "triple_count": "12000"}


BASE = "http://localhost:8000"


def test_catalogue_graph_type():
    g = build_catalogue_graph(
        base_url=BASE,
        title="Test Catalogue",
        description="desc",
        artefact_count=5,
        sparql_endpoint=f"{BASE}/api/v1/sparql/content",
    )
    cat = URIRef(f"{BASE}/mod/")
    assert (cat, RDF.type, MOD.SemanticArtefactCatalog) in g
    assert (cat, DCTERMS.title, None) in [(s, p, None) for s, p, o in g if str(p) == str(DCTERMS.title)]


def test_artefact_graph_type_and_id():
    g = build_artefact_graph(
        ontology=_ontology(),
        version=_version(),
        meta=_meta(),
        stats=_stats(),
        base_url=BASE,
    )
    artefact = URIRef("http://purl.obolibrary.org/obo/go.owl")
    assert (artefact, RDF.type, MOD.SemanticArtefact) in g
    assert (artefact, RDF.type, OWL.Ontology) in g


def test_artefact_graph_acronym():
    g = build_artefact_graph(ontology=_ontology(), version=_version(), meta=_meta(), stats=_stats(), base_url=BASE)
    artefact = URIRef("http://purl.obolibrary.org/obo/go.owl")
    acronyms = [str(o) for _, p, o in g if str(p) == str(MOD.acronym)]
    assert "go" in acronyms


def test_artefact_graph_stats():
    g = build_artefact_graph(ontology=_ontology(), version=_version(), meta=_meta(), stats=_stats(), base_url=BASE)
    artefact = URIRef("http://purl.obolibrary.org/obo/go.owl")
    classes = [str(o) for _, p, o in g if str(p) == str(MOD.numberOfClasses)]
    assert classes == ["5000"]


def test_artefact_graph_no_shortname():
    ont = _ontology(shortname=None)
    g = build_artefact_graph(ontology=ont, version=_version(), meta=_meta(), stats=_stats(), base_url=BASE)
    acronyms = [o for _, p, o in g if str(p) == str(MOD.acronym)]
    assert len(acronyms) == 0


def test_artefacts_list_graph_hydra_collection():
    onts = [(_ontology(), _version(), _meta(), _stats())]
    g = build_artefacts_list_graph(artefacts=onts, total=1, page=1, page_size=10, base_url=BASE)
    col = URIRef(f"{BASE}/mod/artefacts")
    assert (col, RDF.type, HYDRA.Collection) in g


def test_record_graph_type():
    g = build_record_graph(ontology=_ontology(), version=_version(), base_url=BASE)
    from rdflib.namespace import FOAF
    rec = URIRef(f"{BASE}/mod/records/go")
    assert (rec, RDF.type, DCAT.CatalogRecord) in g
    assert (rec, FOAF.primaryTopic, URIRef("http://purl.obolibrary.org/obo/go.owl")) in g


def test_distribution_graph_media_type():
    g = build_distribution_graph(ontology=_ontology(), version=_version(), base_url=BASE)
    dist = URIRef(f"{BASE}/mod/artefacts/go/distributions/v1")
    assert (dist, RDF.type, DCAT.Distribution) in g
    media_types = [str(o) for _, p, o in g if str(p) == str(DCAT.mediaType)]
    assert "application/owl+xml" in media_types


def test_resources_summary_graph():
    stats = {"class_count": "100", "property_count": "10", "individual_count": "5"}
    g = build_resources_summary_graph(ontology=_ontology(), version=_version(), stats=stats, base_url=BASE)
    assert len(list(g)) > 0


def test_resource_list_graph_hydra():
    terms = [{"iri": "http://ex.org/Class1", "label": "Class 1"}]
    g = build_resource_list_graph(
        ontology=_ontology(), version=_version(), terms=terms,
        entity_type="class", total=1, page=1, page_size=10, base_url=BASE,
    )
    collections = [(s, p, o) for s, p, o in g if str(p) == str(RDF.type) and str(o) == str(HYDRA.Collection)]
    assert len(collections) > 0


def test_search_results_graph():
    results = [{"ontology_id": "abc1", "iri": "http://ex.org/C1", "label": "Foo", "score": 1.0}]
    g = build_search_results_graph(results=results, q="foo", total=1, page=1, page_size=10, base_url=BASE)
    assert len(list(g)) > 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /path/to/ontoexplorer && uv run pytest tests/unit/test_mod_builder.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Create builder.py**

```python
# ontoexplorer/modules/mod/builder.py
from datetime import UTC, datetime
from typing import Any

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS, FOAF, OWL, RDF, RDFS, SKOS, XSD

DCAT = Namespace("http://www.w3.org/ns/dcat#")
MOD = Namespace("https://w3id.org/mod#")
VOID = Namespace("http://rdfs.org/ns/void#")
VANN = Namespace("http://purl.org/vocab/vann/")
SCHEMA = Namespace("https://schema.org/")
HYDRA = Namespace("http://www.w3.org/ns/hydra/core#")
SD = Namespace("http://www.w3.org/ns/sparql-service-description#")

MEDIA_TYPES: dict[str, str] = {
    "owl": "application/owl+xml",
    "ttl": "text/turtle",
    "turtle": "text/turtle",
    "rdf": "application/rdf+xml",
    "xml": "application/rdf+xml",
    "nt": "application/n-triples",
    "obo": "text/obo",
    "json": "application/ld+json",
    "jsonld": "application/ld+json",
}

STATUS_URIS: dict[str, str] = {
    "ready": "https://w3id.org/mod#Released",
    "deprecated": "https://w3id.org/mod#Obsolete",
    "ingested": "https://w3id.org/mod#Draft",
    "reasoning": "https://w3id.org/mod#Draft",
}


def _bind(g: Graph) -> None:
    g.bind("dcterms", DCTERMS)
    g.bind("dcat", DCAT)
    g.bind("mod", MOD)
    g.bind("owl", OWL)
    g.bind("foaf", FOAF)
    g.bind("skos", SKOS)
    g.bind("void", VOID)
    g.bind("vann", VANN)
    g.bind("schema", SCHEMA)
    g.bind("hydra", HYDRA)
    g.bind("sd", SD)
    g.bind("rdfs", RDFS)
    g.bind("xsd", XSD)


def _add_str(g: Graph, s: URIRef, p: Any, val: Any) -> None:
    if val:
        g.add((s, p, Literal(str(val))))


def _add_uri_or_str(g: Graph, s: URIRef, p: Any, val: str | None) -> None:
    if val:
        g.add((s, p, URIRef(val) if val.startswith("http") else Literal(val)))


def _artefact_id(ontology: Any) -> str:
    return ontology.shortname or ontology.id


def build_catalogue_graph(
    *,
    base_url: str,
    title: str,
    description: str,
    artefact_count: int,
    sparql_endpoint: str,
) -> Graph:
    g = Graph()
    _bind(g)
    cat = URIRef(f"{base_url}/mod/")
    g.add((cat, RDF.type, MOD.SemanticArtefactCatalog))
    g.add((cat, RDF.type, DCAT.Catalog))
    g.add((cat, DCTERMS.title, Literal(title)))
    g.add((cat, DCTERMS.description, Literal(description)))
    g.add((cat, MOD.numberOfArtefacts, Literal(artefact_count, datatype=XSD.integer)))
    ep = URIRef(sparql_endpoint)
    g.add((ep, RDF.type, SD.Service))
    g.add((cat, SD.endpoint, ep))
    g.add((cat, DCAT.dataset, URIRef(f"{base_url}/mod/artefacts")))
    return g


def build_artefact_graph(
    *,
    ontology: Any,
    version: Any,
    meta: dict,
    stats: dict,
    base_url: str,
) -> Graph:
    g = Graph()
    _bind(g)
    a = URIRef(ontology.iri)
    g.add((a, RDF.type, MOD.SemanticArtefact))
    g.add((a, RDF.type, OWL.Ontology))
    if ontology.shortname:
        g.add((a, MOD.acronym, Literal(ontology.shortname)))
    _add_str(g, a, DCTERMS.title, meta.get("title") or ontology.title)
    _add_str(g, a, DCTERMS.description, meta.get("description"))
    _add_str(g, a, DCTERMS.creator, meta.get("creator"))
    _add_str(g, a, DCTERMS.contributor, meta.get("contributor"))
    _add_str(g, a, DCTERMS.publisher, meta.get("publisher"))
    _add_uri_or_str(g, a, DCTERMS.license, meta.get("license"))
    _add_uri_or_str(g, a, FOAF.homepage, meta.get("homepage"))
    _add_str(g, a, OWL.versionInfo, meta.get("version_info"))
    if version.version_iri:
        g.add((a, OWL.versionIRI, URIRef(version.version_iri)))
    _add_str(g, a, DCTERMS.language, meta.get("language"))
    _add_str(g, a, SCHEMA.citation, meta.get("citation"))
    _add_str(g, a, SCHEMA.funding, meta.get("funding"))
    _add_str(g, a, VANN.preferredNamespacePrefix, meta.get("prefix"))
    _add_uri_or_str(g, a, VANN.preferredNamespaceUri, meta.get("namespace_uri"))
    g.add((a, DCTERMS.created, Literal(ontology.created_at.isoformat(), datatype=XSD.dateTime)))
    g.add((a, DCTERMS.modified, Literal(version.created_at.isoformat(), datatype=XSD.dateTime)))
    if (n := stats.get("class_count")) is not None:
        g.add((a, MOD.numberOfClasses, Literal(int(n), datatype=XSD.integer)))
    if (n := stats.get("property_count")) is not None:
        g.add((a, MOD.numberOfProperties, Literal(int(n), datatype=XSD.integer)))
    if (n := stats.get("individual_count")) is not None:
        g.add((a, MOD.numberOfIndividuals, Literal(int(n), datatype=XSD.integer)))
    triple_count = stats.get("triple_count") or getattr(version, "triple_count", None)
    if triple_count is not None:
        g.add((a, VOID.triples, Literal(int(triple_count), datatype=XSD.integer)))
    if status_uri := STATUS_URIS.get(version.status):
        g.add((a, MOD.status, URIRef(status_uri)))
    aid = _artefact_id(ontology)
    dist_uri = URIRef(f"{base_url}/mod/artefacts/{aid}/distributions/{version.id}")
    g.add((a, DCAT.distribution, dist_uri))
    return g


def build_artefacts_list_graph(
    *,
    artefacts: list[tuple[Any, Any, dict, dict]],  # (ontology, version, meta, stats)
    total: int,
    page: int,
    page_size: int,
    base_url: str,
) -> Graph:
    g = Graph()
    _bind(g)
    col = URIRef(f"{base_url}/mod/artefacts")
    g.add((col, RDF.type, HYDRA.Collection))
    g.add((col, HYDRA.totalItems, Literal(total, datatype=XSD.integer)))
    g.add((col, HYDRA.itemsPerPage, Literal(page_size, datatype=XSD.integer)))
    _add_pagination(g, col, f"{base_url}/mod/artefacts", total, page, page_size)
    for ontology, version, meta, stats in artefacts:
        artefact_g = build_artefact_graph(
            ontology=ontology, version=version, meta=meta, stats=stats, base_url=base_url
        )
        for triple in artefact_g:
            g.add(triple)
        g.add((col, HYDRA.member, URIRef(ontology.iri)))
    return g


def build_record_graph(*, ontology: Any, version: Any, base_url: str) -> Graph:
    g = Graph()
    _bind(g)
    aid = _artefact_id(ontology)
    rec = URIRef(f"{base_url}/mod/records/{aid}")
    g.add((rec, RDF.type, DCAT.CatalogRecord))
    g.add((rec, FOAF.primaryTopic, URIRef(ontology.iri)))
    g.add((rec, DCTERMS.created, Literal(ontology.created_at.isoformat(), datatype=XSD.dateTime)))
    g.add((rec, DCTERMS.modified, Literal(version.created_at.isoformat(), datatype=XSD.dateTime)))
    return g


def build_records_list_graph(
    *,
    records: list[tuple[Any, Any]],  # (ontology, version)
    total: int,
    page: int,
    page_size: int,
    base_url: str,
) -> Graph:
    g = Graph()
    _bind(g)
    col = URIRef(f"{base_url}/mod/records")
    g.add((col, RDF.type, HYDRA.Collection))
    g.add((col, HYDRA.totalItems, Literal(total, datatype=XSD.integer)))
    _add_pagination(g, col, f"{base_url}/mod/records", total, page, page_size)
    for ontology, version in records:
        rec_g = build_record_graph(ontology=ontology, version=version, base_url=base_url)
        for triple in rec_g:
            g.add(triple)
        g.add((col, HYDRA.member, URIRef(f"{base_url}/mod/records/{_artefact_id(ontology)}")))
    return g


def build_distribution_graph(*, ontology: Any, version: Any, base_url: str) -> Graph:
    g = Graph()
    _bind(g)
    aid = _artefact_id(ontology)
    dist = URIRef(f"{base_url}/mod/artefacts/{aid}/distributions/{version.id}")
    g.add((dist, RDF.type, DCAT.Distribution))
    download_url = URIRef(f"{base_url}/api/v1/ontologies/{ontology.id}/{version.id}/download")
    g.add((dist, DCAT.accessURL, download_url))
    g.add((dist, DCAT.downloadURL, download_url))
    g.add((dist, DCTERMS.format, Literal(version.format)))
    media_type = MEDIA_TYPES.get(version.format, f"application/{version.format}")
    g.add((dist, DCAT.mediaType, Literal(media_type)))
    g.add((dist, DCTERMS.created, Literal(version.created_at.isoformat(), datatype=XSD.dateTime)))
    return g


def build_distributions_list_graph(
    *, ontology: Any, versions: list[Any], base_url: str
) -> Graph:
    g = Graph()
    _bind(g)
    aid = _artefact_id(ontology)
    col = URIRef(f"{base_url}/mod/artefacts/{aid}/distributions")
    g.add((col, RDF.type, HYDRA.Collection))
    g.add((col, HYDRA.totalItems, Literal(len(versions), datatype=XSD.integer)))
    for version in versions:
        dist_g = build_distribution_graph(ontology=ontology, version=version, base_url=base_url)
        for triple in dist_g:
            g.add(triple)
        g.add((col, HYDRA.member, URIRef(f"{base_url}/mod/artefacts/{aid}/distributions/{version.id}")))
    return g


ENTITY_TYPE_TO_RDF = {
    "class": OWL.Class,
    "individual": OWL.NamedIndividual,
    "property": RDF.Property,
    "concept": SKOS.Concept,
    "scheme": SKOS.ConceptScheme,
    "collection": SKOS.Collection,
}


def build_resources_summary_graph(*, ontology: Any, version: Any, stats: dict, base_url: str) -> Graph:
    g = Graph()
    _bind(g)
    a = URIRef(ontology.iri)
    if (n := stats.get("class_count")) is not None:
        g.add((a, MOD.numberOfClasses, Literal(int(n), datatype=XSD.integer)))
    if (n := stats.get("property_count")) is not None:
        g.add((a, MOD.numberOfProperties, Literal(int(n), datatype=XSD.integer)))
    if (n := stats.get("individual_count")) is not None:
        g.add((a, MOD.numberOfIndividuals, Literal(int(n), datatype=XSD.integer)))
    return g


def build_resource_list_graph(
    *,
    ontology: Any,
    version: Any,
    terms: list[dict],
    entity_type: str,
    total: int,
    page: int,
    page_size: int,
    base_url: str,
) -> Graph:
    g = Graph()
    _bind(g)
    aid = _artefact_id(ontology)
    col_url = f"{base_url}/mod/artefacts/{aid}/resources/{entity_type}s"
    col = URIRef(col_url)
    g.add((col, RDF.type, HYDRA.Collection))
    g.add((col, HYDRA.totalItems, Literal(total, datatype=XSD.integer)))
    _add_pagination(g, col, col_url, total, page, page_size)
    rdf_type = ENTITY_TYPE_TO_RDF.get(entity_type, OWL.Class)
    for term in terms:
        node = URIRef(term["iri"])
        g.add((node, RDF.type, rdf_type))
        if label := term.get("label"):
            g.add((node, RDFS.label, Literal(label)))
        g.add((col, HYDRA.member, node))
    return g


def build_labels_graph(*, ontology: Any, version: Any, terms: list[dict], base_url: str) -> Graph:
    g = Graph()
    _bind(g)
    for term in terms:
        node = URIRef(term["iri"])
        if label := term.get("label"):
            lang = term.get("lang")
            g.add((node, RDFS.label, Literal(label, lang=lang) if lang else Literal(label)))
    return g


def build_search_results_graph(
    *,
    results: list[dict],
    q: str,
    total: int,
    page: int,
    page_size: int,
    base_url: str,
) -> Graph:
    g = Graph()
    _bind(g)
    col = URIRef(f"{base_url}/mod/search")
    g.add((col, RDF.type, HYDRA.Collection))
    g.add((col, HYDRA.totalItems, Literal(total, datatype=XSD.integer)))
    for result in results:
        iri = result.get("iri") or result.get("ontology_iri")
        if iri:
            node = URIRef(iri)
            g.add((col, HYDRA.member, node))
            if label := result.get("label"):
                g.add((node, RDFS.label, Literal(label)))
    return g


def _add_pagination(g: Graph, col: URIRef, base: str, total: int, page: int, page_size: int) -> None:
    view = URIRef(f"{base}?page={page}&page_size={page_size}")
    g.add((col, HYDRA.view, view))
    if page > 1:
        g.add((view, HYDRA.previous, URIRef(f"{base}?page={page - 1}&page_size={page_size}")))
    if page * page_size < total:
        g.add((view, HYDRA.next, URIRef(f"{base}?page={page + 1}&page_size={page_size}")))
    g.add((view, HYDRA.first, URIRef(f"{base}?page=1&page_size={page_size}")))
    last_page = max(1, (total + page_size - 1) // page_size)
    g.add((view, HYDRA.last, URIRef(f"{base}?page={last_page}&page_size={page_size}")))
```

- [ ] **Step 4: Run tests to confirm pass**

```bash
cd /path/to/ontoexplorer && uv run pytest tests/unit/test_mod_builder.py -v
```

Expected: all 12 tests pass.

- [ ] **Step 5: Commit**

```bash
git add ontoexplorer/modules/mod/builder.py tests/unit/test_mod_builder.py
git commit -m "feat(mod): add graph builder functions for all endpoint groups"
```

---

## Task 6: Router — all endpoints + wire up

**Files:**
- Create: `ontoexplorer/api/mod.py`
- Modify: `ontoexplorer/main.py`

The router resolves `{artefact_id}` (shortname or URL-decoded IRI), queries DB, fetches stats from Redis, and returns `RDFResponse`. Content negotiation via `?format=` param or `Accept` header.

- [ ] **Step 1: Create ontoexplorer/api/mod.py**

```python
# ontoexplorer/api/mod.py
import asyncio
import json
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.config import get_settings
from ontoexplorer.database import get_db
from ontoexplorer.models.db import Ontology, OntologyMetaProfile, OntologyVersion
from ontoexplorer.modules.mod.builder import (
    build_artefact_graph,
    build_artefacts_list_graph,
    build_catalogue_graph,
    build_distribution_graph,
    build_distributions_list_graph,
    build_labels_graph,
    build_record_graph,
    build_records_list_graph,
    build_resource_list_graph,
    build_resources_summary_graph,
    build_search_results_graph,
)
from ontoexplorer.modules.mod.ratelimit import mod_rate_limit
from ontoexplorer.modules.mod.response import RDFResponse

router = APIRouter(tags=["mod"])

_FORMAT_PARAM = Query(None, description="Response format: jsonld, ttl, rdfxml, html")
_PAGE_PARAM = Query(1, ge=1, description="Page number")
_PAGE_SIZE_PARAM = Query(20, ge=1, le=200, description="Items per page")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _base_url(request: Request) -> str:
    s = get_settings()
    return str(s.app_url).rstrip("/")


def _get_stats(version_id: str) -> dict:
    try:
        from ontoexplorer.modules.search.indexer import _get_redis, _stats_cache_key
        raw = _get_redis().get(_stats_cache_key(version_id))
        return json.loads(raw) if raw else {}
    except Exception:
        return {}


async def _fetch_stats(version_id: str) -> dict:
    return await asyncio.to_thread(_get_stats, version_id)


async def _resolve_artefact(
    artefact_id: str, db: AsyncSession
) -> tuple[Ontology, OntologyVersion]:
    decoded = unquote(artefact_id)
    stmt = (
        select(Ontology, OntologyVersion)
        .join(OntologyVersion, OntologyVersion.ontology_id == Ontology.id)
        .where(
            (Ontology.shortname == decoded) | (Ontology.iri == decoded),
            OntologyVersion.status == "ready",
        )
        .order_by(OntologyVersion.created_at.desc())
        .limit(1)
    )
    row = (await db.execute(stmt)).first()
    if not row:
        raise HTTPException(status_code=404, detail="Artefact not found")
    return row.Ontology, row.OntologyVersion


async def _fetch_meta(version_id: str, db: AsyncSession) -> dict:
    result = await db.execute(
        select(OntologyMetaProfile.resolved).where(OntologyMetaProfile.version_id == version_id)
    )
    row = result.scalar_one_or_none()
    return row or {}


async def _ready_ontologies_with_latest(
    db: AsyncSession, q: str | None = None, page: int = 1, page_size: int = 20
) -> tuple[list[tuple[Ontology, OntologyVersion]], int]:
    subq = (
        select(OntologyVersion.ontology_id, func.max(OntologyVersion.created_at).label("max_created"))
        .where(OntologyVersion.status == "ready")
        .group_by(OntologyVersion.ontology_id)
        .subquery()
    )
    base_stmt = (
        select(Ontology, OntologyVersion)
        .join(subq, Ontology.id == subq.c.ontology_id)
        .join(
            OntologyVersion,
            (OntologyVersion.ontology_id == subq.c.ontology_id)
            & (OntologyVersion.created_at == subq.c.max_created),
        )
    )
    if q:
        q_lower = f"%{q.lower()}%"
        base_stmt = base_stmt.where(
            (func.lower(Ontology.title).like(q_lower))
            | (func.lower(Ontology.shortname).like(q_lower))
        )
    count_stmt = select(func.count()).select_from(base_stmt.subquery())
    total = (await db.execute(count_stmt)).scalar_one()
    rows = (await db.execute(base_stmt.offset((page - 1) * page_size).limit(page_size))).all()
    return [(row.Ontology, row.OntologyVersion) for row in rows], total


# ── Catalogue ─────────────────────────────────────────────────────────────────

@router.get("/mod/", dependencies=[Depends(mod_rate_limit)])
async def get_catalogue(
    request: Request,
    fmt: str | None = _FORMAT_PARAM,
    db: AsyncSession = Depends(get_db),
):
    settings = get_settings()
    base = _base_url(request)
    total = (await db.execute(
        select(func.count(Ontology.id)).where(
            Ontology.id.in_(
                select(OntologyVersion.ontology_id).where(OntologyVersion.status == "ready")
            )
        )
    )).scalar_one()
    graph = build_catalogue_graph(
        base_url=base,
        title=settings.mod_catalogue_title,
        description=settings.mod_catalogue_description,
        artefact_count=total,
        sparql_endpoint=f"{base}/api/v1/sparql/content",
    )
    return RDFResponse(graph, format_param=fmt, accept=request.headers.get("accept"))


# ── Records ───────────────────────────────────────────────────────────────────

@router.get("/mod/records", dependencies=[Depends(mod_rate_limit)])
async def list_records(
    request: Request,
    fmt: str | None = _FORMAT_PARAM,
    page: int = _PAGE_PARAM,
    page_size: int = _PAGE_SIZE_PARAM,
    db: AsyncSession = Depends(get_db),
):
    base = _base_url(request)
    pairs, total = await _ready_ontologies_with_latest(db, page=page, page_size=page_size)
    graph = build_records_list_graph(records=pairs, total=total, page=page, page_size=page_size, base_url=base)
    return RDFResponse(graph, format_param=fmt, accept=request.headers.get("accept"))


@router.get("/mod/records/{artefact_id}", dependencies=[Depends(mod_rate_limit)])
async def get_record(
    artefact_id: str,
    request: Request,
    fmt: str | None = _FORMAT_PARAM,
    db: AsyncSession = Depends(get_db),
):
    ontology, version = await _resolve_artefact(artefact_id, db)
    graph = build_record_graph(ontology=ontology, version=version, base_url=_base_url(request))
    return RDFResponse(graph, format_param=fmt, accept=request.headers.get("accept"))


# ── Artefacts ─────────────────────────────────────────────────────────────────

@router.get("/mod/artefacts", dependencies=[Depends(mod_rate_limit)])
async def list_artefacts(
    request: Request,
    fmt: str | None = _FORMAT_PARAM,
    q: str | None = Query(None, description="Filter by title or acronym"),
    page: int = _PAGE_PARAM,
    page_size: int = _PAGE_SIZE_PARAM,
    db: AsyncSession = Depends(get_db),
):
    base = _base_url(request)
    pairs, total = await _ready_ontologies_with_latest(db, q=q, page=page, page_size=page_size)
    artefacts = []
    for ontology, version in pairs:
        meta = await _fetch_meta(version.id, db)
        stats = await _fetch_stats(version.id)
        artefacts.append((ontology, version, meta, stats))
    graph = build_artefacts_list_graph(artefacts=artefacts, total=total, page=page, page_size=page_size, base_url=base)
    return RDFResponse(graph, format_param=fmt, accept=request.headers.get("accept"))


@router.get("/mod/artefacts/{artefact_id}/record", dependencies=[Depends(mod_rate_limit)])
async def get_artefact_record(
    artefact_id: str,
    request: Request,
    fmt: str | None = _FORMAT_PARAM,
    db: AsyncSession = Depends(get_db),
):
    ontology, version = await _resolve_artefact(artefact_id, db)
    graph = build_record_graph(ontology=ontology, version=version, base_url=_base_url(request))
    return RDFResponse(graph, format_param=fmt, accept=request.headers.get("accept"))


@router.get("/mod/artefacts/{artefact_id}/distributions/latest", dependencies=[Depends(mod_rate_limit)])
async def get_latest_distribution(
    artefact_id: str,
    request: Request,
    fmt: str | None = _FORMAT_PARAM,
    db: AsyncSession = Depends(get_db),
):
    ontology, version = await _resolve_artefact(artefact_id, db)
    graph = build_distribution_graph(ontology=ontology, version=version, base_url=_base_url(request))
    return RDFResponse(graph, format_param=fmt, accept=request.headers.get("accept"))


@router.get("/mod/artefacts/{artefact_id}/distributions/{distribution_id}", dependencies=[Depends(mod_rate_limit)])
async def get_distribution(
    artefact_id: str,
    distribution_id: str,
    request: Request,
    fmt: str | None = _FORMAT_PARAM,
    db: AsyncSession = Depends(get_db),
):
    decoded = unquote(artefact_id)
    stmt = (
        select(Ontology, OntologyVersion)
        .join(OntologyVersion, OntologyVersion.ontology_id == Ontology.id)
        .where(
            (Ontology.shortname == decoded) | (Ontology.iri == decoded),
            OntologyVersion.id == distribution_id,
        )
        .limit(1)
    )
    row = (await db.execute(stmt)).first()
    if not row:
        raise HTTPException(status_code=404, detail="Distribution not found")
    graph = build_distribution_graph(ontology=row.Ontology, version=row.OntologyVersion, base_url=_base_url(request))
    return RDFResponse(graph, format_param=fmt, accept=request.headers.get("accept"))


@router.get("/mod/artefacts/{artefact_id}/distributions", dependencies=[Depends(mod_rate_limit)])
async def list_distributions(
    artefact_id: str,
    request: Request,
    fmt: str | None = _FORMAT_PARAM,
    db: AsyncSession = Depends(get_db),
):
    decoded = unquote(artefact_id)
    ont_result = await db.execute(
        select(Ontology).where((Ontology.shortname == decoded) | (Ontology.iri == decoded))
    )
    ontology = ont_result.scalar_one_or_none()
    if not ontology:
        raise HTTPException(status_code=404, detail="Artefact not found")
    versions_result = await db.execute(
        select(OntologyVersion)
        .where(OntologyVersion.ontology_id == ontology.id)
        .order_by(OntologyVersion.created_at.desc())
    )
    versions = list(versions_result.scalars().all())
    graph = build_distributions_list_graph(ontology=ontology, versions=versions, base_url=_base_url(request))
    return RDFResponse(graph, format_param=fmt, accept=request.headers.get("accept"))


@router.get("/mod/artefacts/{artefact_id}", dependencies=[Depends(mod_rate_limit)])
async def get_artefact(
    artefact_id: str,
    request: Request,
    fmt: str | None = _FORMAT_PARAM,
    db: AsyncSession = Depends(get_db),
):
    ontology, version = await _resolve_artefact(artefact_id, db)
    meta = await _fetch_meta(version.id, db)
    stats = await _fetch_stats(version.id)
    graph = build_artefact_graph(ontology=ontology, version=version, meta=meta, stats=stats, base_url=_base_url(request))
    return RDFResponse(graph, format_param=fmt, accept=request.headers.get("accept"))


# ── Resources ─────────────────────────────────────────────────────────────────

async def _sparql_terms(ontology_id: str, version_id: str, entity_type: str, limit: int, offset: int) -> list[dict]:
    TYPE_SPARQL = {
        "class": "owl:Class",
        "property": "rdf:Property",
        "individual": "owl:NamedIndividual",
        "concept": "skos:Concept",
        "scheme": "skos:ConceptScheme",
        "collection": "skos:Collection",
    }
    rdf_type = TYPE_SPARQL.get(entity_type, "owl:Class")
    graph_iri = f"urn:ontology:{ontology_id}:{version_id}"
    sparql = f"""
PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
SELECT DISTINCT ?uri ?label WHERE {{
  GRAPH <{graph_iri}> {{
    ?uri a {rdf_type} .
    OPTIONAL {{ ?uri rdfs:label ?label FILTER(langMatches(lang(?label), "en") || lang(?label) = "") }}
  }}
}} ORDER BY ?uri LIMIT {limit} OFFSET {offset}
"""

    def _run() -> list[dict]:
        from ontoexplorer.clients.oxigraph import get_store
        store = get_store()
        results = store.query(sparql)
        terms = []
        for row in results:
            terms.append({
                "iri": str(row["uri"]),  # type: ignore[index]
                "label": str(row["label"]) if row.get("label") else None,  # type: ignore[index]
            })
        return terms

    return await asyncio.to_thread(_run)


async def _sparql_term_count(ontology_id: str, version_id: str, entity_type: str) -> int:
    TYPE_SPARQL = {
        "class": "owl:Class",
        "property": "rdf:Property",
        "individual": "owl:NamedIndividual",
        "concept": "skos:Concept",
        "scheme": "skos:ConceptScheme",
        "collection": "skos:Collection",
    }
    rdf_type = TYPE_SPARQL.get(entity_type, "owl:Class")
    graph_iri = f"urn:ontology:{ontology_id}:{version_id}"
    sparql = f"""
PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
SELECT (COUNT(DISTINCT ?uri) AS ?count) WHERE {{
  GRAPH <{graph_iri}> {{ ?uri a {rdf_type} . }}
}}
"""

    def _run() -> int:
        from ontoexplorer.clients.oxigraph import get_store
        store = get_store()
        results = list(get_store().query(sparql))
        if results:
            return int(str(results[0]["count"]))  # type: ignore[index]
        return 0

    return await asyncio.to_thread(_run)


@router.get("/mod/artefacts/{artefact_id}/resources", dependencies=[Depends(mod_rate_limit)])
async def get_resources_summary(
    artefact_id: str,
    request: Request,
    fmt: str | None = _FORMAT_PARAM,
    db: AsyncSession = Depends(get_db),
):
    ontology, version = await _resolve_artefact(artefact_id, db)
    stats = await _fetch_stats(version.id)
    graph = build_resources_summary_graph(ontology=ontology, version=version, stats=stats, base_url=_base_url(request))
    return RDFResponse(graph, format_param=fmt, accept=request.headers.get("accept"))


async def _resource_endpoint(
    artefact_id: str, entity_type: str, request: Request,
    fmt: str | None, page: int, page_size: int, db: AsyncSession,
):
    ontology, version = await _resolve_artefact(artefact_id, db)
    base = _base_url(request)
    offset = (page - 1) * page_size
    terms, total = await asyncio.gather(
        _sparql_terms(ontology.id, version.id, entity_type, page_size, offset),
        _sparql_term_count(ontology.id, version.id, entity_type),
    )
    graph = build_resource_list_graph(
        ontology=ontology, version=version, terms=terms,
        entity_type=entity_type, total=total, page=page, page_size=page_size, base_url=base,
    )
    return RDFResponse(graph, format_param=fmt, accept=request.headers.get("accept"))


@router.get("/mod/artefacts/{artefact_id}/resources/classes", dependencies=[Depends(mod_rate_limit)])
async def get_classes(artefact_id: str, request: Request, fmt: str | None = _FORMAT_PARAM, page: int = _PAGE_PARAM, page_size: int = _PAGE_SIZE_PARAM, db: AsyncSession = Depends(get_db)):
    return await _resource_endpoint(artefact_id, "class", request, fmt, page, page_size, db)


@router.get("/mod/artefacts/{artefact_id}/resources/properties", dependencies=[Depends(mod_rate_limit)])
async def get_properties(artefact_id: str, request: Request, fmt: str | None = _FORMAT_PARAM, page: int = _PAGE_PARAM, page_size: int = _PAGE_SIZE_PARAM, db: AsyncSession = Depends(get_db)):
    return await _resource_endpoint(artefact_id, "property", request, fmt, page, page_size, db)


@router.get("/mod/artefacts/{artefact_id}/resources/individuals", dependencies=[Depends(mod_rate_limit)])
async def get_individuals(artefact_id: str, request: Request, fmt: str | None = _FORMAT_PARAM, page: int = _PAGE_PARAM, page_size: int = _PAGE_SIZE_PARAM, db: AsyncSession = Depends(get_db)):
    return await _resource_endpoint(artefact_id, "individual", request, fmt, page, page_size, db)


@router.get("/mod/artefacts/{artefact_id}/resources/concepts", dependencies=[Depends(mod_rate_limit)])
async def get_concepts(artefact_id: str, request: Request, fmt: str | None = _FORMAT_PARAM, page: int = _PAGE_PARAM, page_size: int = _PAGE_SIZE_PARAM, db: AsyncSession = Depends(get_db)):
    return await _resource_endpoint(artefact_id, "concept", request, fmt, page, page_size, db)


@router.get("/mod/artefacts/{artefact_id}/resources/schemes", dependencies=[Depends(mod_rate_limit)])
async def get_schemes(artefact_id: str, request: Request, fmt: str | None = _FORMAT_PARAM, page: int = _PAGE_PARAM, page_size: int = _PAGE_SIZE_PARAM, db: AsyncSession = Depends(get_db)):
    return await _resource_endpoint(artefact_id, "scheme", request, fmt, page, page_size, db)


@router.get("/mod/artefacts/{artefact_id}/resources/collections", dependencies=[Depends(mod_rate_limit)])
async def get_collections(artefact_id: str, request: Request, fmt: str | None = _FORMAT_PARAM, page: int = _PAGE_PARAM, page_size: int = _PAGE_SIZE_PARAM, db: AsyncSession = Depends(get_db)):
    return await _resource_endpoint(artefact_id, "collection", request, fmt, page, page_size, db)


@router.get("/mod/artefacts/{artefact_id}/resources/labels", dependencies=[Depends(mod_rate_limit)])
async def get_labels(
    artefact_id: str,
    request: Request,
    fmt: str | None = _FORMAT_PARAM,
    page: int = _PAGE_PARAM,
    page_size: int = _PAGE_SIZE_PARAM,
    db: AsyncSession = Depends(get_db),
):
    ontology, version = await _resolve_artefact(artefact_id, db)
    graph_iri_str = f"urn:ontology:{ontology.id}:{version.id}"
    offset = (page - 1) * page_size
    sparql = f"""
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?uri ?label WHERE {{
  GRAPH <{graph_iri_str}> {{ ?uri rdfs:label ?label }}
}} ORDER BY ?uri LIMIT {page_size} OFFSET {offset}
"""

    def _run() -> list[dict]:
        from ontoexplorer.clients.oxigraph import get_store
        results = get_store().query(sparql)
        return [
            {"iri": str(r["uri"]), "label": str(r["label"]), "lang": r["label"].language or None}  # type: ignore[index]
            for r in results
        ]

    terms = await asyncio.to_thread(_run)
    graph = build_labels_graph(ontology=ontology, version=version, terms=terms, base_url=_base_url(request))
    return RDFResponse(graph, format_param=fmt, accept=request.headers.get("accept"))


# ── Search ────────────────────────────────────────────────────────────────────

async def _mod_search(q: str, db: AsyncSession, content_only: bool = False, metadata_only: bool = False) -> list[dict]:
    results: list[dict] = []
    if not metadata_only:
        # Content search: use existing global search
        from ontoexplorer.api.global_search import _latest_ingested_versions, _entity_search
        versions = await _latest_ingested_versions(db)
        for version in versions[:10]:  # limit to avoid timeout
            try:
                hits = await _entity_search(version, q, lang=None, limit=5)
                for hit in hits:
                    results.append({
                        "iri": hit.get("iri", ""),
                        "label": hit.get("label", ""),
                        "ontology_id": version.ontology_id,
                    })
            except Exception:
                pass
    if not content_only:
        # Metadata search: filter ontologies by title/shortname
        rows = await db.execute(
            select(Ontology).where(
                (func.lower(Ontology.title).like(f"%{q.lower()}%"))
                | (func.lower(Ontology.shortname).like(f"%{q.lower()}%"))
            ).limit(20)
        )
        for ont in rows.scalars():
            results.append({"iri": ont.iri, "label": ont.title or ont.shortname or "", "ontology_id": ont.id})
    return results


@router.get("/mod/search", dependencies=[Depends(mod_rate_limit)])
async def mod_search(
    request: Request,
    q: str = Query(..., min_length=1),
    fmt: str | None = _FORMAT_PARAM,
    page: int = _PAGE_PARAM,
    page_size: int = _PAGE_SIZE_PARAM,
    db: AsyncSession = Depends(get_db),
):
    base = _base_url(request)
    results = await _mod_search(q, db)
    graph = build_search_results_graph(results=results, q=q, total=len(results), page=page, page_size=page_size, base_url=base)
    return RDFResponse(graph, format_param=fmt, accept=request.headers.get("accept"))


@router.get("/mod/search/content", dependencies=[Depends(mod_rate_limit)])
async def mod_search_content(
    request: Request,
    q: str = Query(..., min_length=1),
    fmt: str | None = _FORMAT_PARAM,
    page: int = _PAGE_PARAM,
    page_size: int = _PAGE_SIZE_PARAM,
    db: AsyncSession = Depends(get_db),
):
    base = _base_url(request)
    results = await _mod_search(q, db, content_only=True)
    graph = build_search_results_graph(results=results, q=q, total=len(results), page=page, page_size=page_size, base_url=base)
    return RDFResponse(graph, format_param=fmt, accept=request.headers.get("accept"))


@router.get("/mod/search/metadata", dependencies=[Depends(mod_rate_limit)])
async def mod_search_metadata(
    request: Request,
    q: str = Query(..., min_length=1),
    fmt: str | None = _FORMAT_PARAM,
    page: int = _PAGE_PARAM,
    page_size: int = _PAGE_SIZE_PARAM,
    db: AsyncSession = Depends(get_db),
):
    base = _base_url(request)
    results = await _mod_search(q, db, metadata_only=True)
    graph = build_search_results_graph(results=results, q=q, total=len(results), page=page, page_size=page_size, base_url=base)
    return RDFResponse(graph, format_param=fmt, accept=request.headers.get("accept"))
```

- [ ] **Step 2: Register mod_router in main.py**

In `ontoexplorer/main.py`, add the import:

```python
from ontoexplorer.api.mod import router as mod_router
```

And register the router after `app.include_router(health_router)`:

```python
    app.include_router(health_router)
    app.include_router(mod_router)          # MOD-API at /mod/*
    app.include_router(auth_router)
    # ... rest unchanged
```

- [ ] **Step 3: Verify the app starts without errors**

```bash
cd /path/to/ontoexplorer && uv run python -c "from ontoexplorer.main import create_app; app = create_app(); print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add ontoexplorer/api/mod.py ontoexplorer/main.py
git commit -m "feat(mod): add 30-endpoint MOD-API router at /mod/"
```

---

## Task 7: Integration tests

**Files:**
- Create: `tests/integration/test_mod_api.py`

- [ ] **Step 1: Write the integration tests**

```python
# tests/integration/test_mod_api.py
"""Integration tests for the MOD-API compatibility layer."""
import json
import uuid
from datetime import datetime, UTC
from unittest.mock import patch

import pytest
from sqlalchemy import insert

from ontoexplorer.models.db import Ontology, OntologyMetaProfile, OntologyVersion


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
async def ready_ontology(db_session):
    ont_id = str(uuid.uuid4())
    ver_id = str(uuid.uuid4())
    await db_session.execute(insert(Ontology).values(
        id=ont_id,
        iri="http://purl.obolibrary.org/obo/go.owl",
        shortname="go",
        title="Gene Ontology",
        groups=[],
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
    ))
    await db_session.execute(insert(OntologyVersion).values(
        id=ver_id,
        ontology_id=ont_id,
        minio_key="go/go.owl",
        sha256="abc123",
        format="owl",
        status="ready",
        triple_count=12000,
        created_at=datetime(2024, 6, 1, tzinfo=UTC),
    ))
    await db_session.execute(insert(OntologyMetaProfile).values(
        id=str(uuid.uuid4()),
        version_id=ver_id,
        resolved={
            "title": "Gene Ontology",
            "description": "A controlled vocabulary for gene function",
            "creator": "GO Consortium",
            "license": "https://creativecommons.org/licenses/by/4.0/",
        },
    ))
    await db_session.commit()
    return ont_id, ver_id


def _no_redis(*args, **kwargs):
    return {}


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_catalogue_returns_jsonld(client, ready_ontology):
    with patch("ontoexplorer.api.mod._get_stats", return_value={}), \
         patch("ontoexplorer.modules.mod.ratelimit._get_redis") as mock_redis:
        mock_redis.return_value.incr.return_value = 1
        mock_redis.return_value.expire.return_value = True
        resp = await client.get("/mod/")
    assert resp.status_code == 200
    assert "application/ld+json" in resp.headers["content-type"]
    data = resp.json()
    assert "@context" in data


@pytest.mark.anyio
async def test_catalogue_returns_turtle(client, ready_ontology):
    with patch("ontoexplorer.api.mod._get_stats", return_value={}), \
         patch("ontoexplorer.modules.mod.ratelimit._get_redis") as mock_redis:
        mock_redis.return_value.incr.return_value = 1
        mock_redis.return_value.expire.return_value = True
        resp = await client.get("/mod/?format=ttl")
    assert resp.status_code == 200
    assert "text/turtle" in resp.headers["content-type"]
    assert b"OntoExplorer" in resp.content


@pytest.mark.anyio
async def test_catalogue_accept_turtle_header(client, ready_ontology):
    with patch("ontoexplorer.api.mod._get_stats", return_value={}), \
         patch("ontoexplorer.modules.mod.ratelimit._get_redis") as mock_redis:
        mock_redis.return_value.incr.return_value = 1
        mock_redis.return_value.expire.return_value = True
        resp = await client.get("/mod/", headers={"Accept": "text/turtle"})
    assert resp.status_code == 200
    assert "text/turtle" in resp.headers["content-type"]


@pytest.mark.anyio
async def test_artefacts_list(client, ready_ontology):
    with patch("ontoexplorer.api.mod._get_stats", return_value={"class_count": "5000"}), \
         patch("ontoexplorer.modules.mod.ratelimit._get_redis") as mock_redis:
        mock_redis.return_value.incr.return_value = 1
        mock_redis.return_value.expire.return_value = True
        resp = await client.get("/mod/artefacts")
    assert resp.status_code == 200
    data = resp.json()
    assert "@context" in data


@pytest.mark.anyio
async def test_get_artefact_by_shortname(client, ready_ontology):
    with patch("ontoexplorer.api.mod._get_stats", return_value={}), \
         patch("ontoexplorer.modules.mod.ratelimit._get_redis") as mock_redis:
        mock_redis.return_value.incr.return_value = 1
        mock_redis.return_value.expire.return_value = True
        resp = await client.get("/mod/artefacts/go")
    assert resp.status_code == 200
    data = resp.json()
    assert "@context" in data


@pytest.mark.anyio
async def test_get_artefact_by_encoded_iri(client, ready_ontology):
    from urllib.parse import quote
    iri = quote("http://purl.obolibrary.org/obo/go.owl", safe="")
    with patch("ontoexplorer.api.mod._get_stats", return_value={}), \
         patch("ontoexplorer.modules.mod.ratelimit._get_redis") as mock_redis:
        mock_redis.return_value.incr.return_value = 1
        mock_redis.return_value.expire.return_value = True
        resp = await client.get(f"/mod/artefacts/{iri}")
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_get_artefact_not_found(client, ready_ontology):
    with patch("ontoexplorer.modules.mod.ratelimit._get_redis") as mock_redis:
        mock_redis.return_value.incr.return_value = 1
        mock_redis.return_value.expire.return_value = True
        resp = await client.get("/mod/artefacts/nonexistent")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_get_record(client, ready_ontology):
    with patch("ontoexplorer.modules.mod.ratelimit._get_redis") as mock_redis:
        mock_redis.return_value.incr.return_value = 1
        mock_redis.return_value.expire.return_value = True
        resp = await client.get("/mod/records/go")
    assert resp.status_code == 200
    data = resp.json()
    assert "@context" in data


@pytest.mark.anyio
async def test_list_distributions(client, ready_ontology):
    with patch("ontoexplorer.modules.mod.ratelimit._get_redis") as mock_redis:
        mock_redis.return_value.incr.return_value = 1
        mock_redis.return_value.expire.return_value = True
        resp = await client.get("/mod/artefacts/go/distributions")
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_artefact_record_subpath(client, ready_ontology):
    with patch("ontoexplorer.modules.mod.ratelimit._get_redis") as mock_redis:
        mock_redis.return_value.incr.return_value = 1
        mock_redis.return_value.expire.return_value = True
        resp = await client.get("/mod/artefacts/go/record")
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_catalogue_html(client, ready_ontology):
    with patch("ontoexplorer.api.mod._get_stats", return_value={}), \
         patch("ontoexplorer.modules.mod.ratelimit._get_redis") as mock_redis:
        mock_redis.return_value.incr.return_value = 1
        mock_redis.return_value.expire.return_value = True
        resp = await client.get("/mod/?format=html")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert b"<table" in resp.content
```

- [ ] **Step 2: Run integration tests**

```bash
cd /path/to/ontoexplorer && uv run pytest tests/integration/test_mod_api.py -v
```

Expected: all 11 tests pass.

- [ ] **Step 3: Run full test suite to confirm no regressions**

```bash
cd /path/to/ontoexplorer && uv run pytest tests/ -v --ignore=tests/integration/test_reasoning.py --ignore=tests/integration/test_reasoning_api.py -x
```

Expected: all existing tests pass.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_mod_api.py
git commit -m "test(mod): add integration tests for MOD-API compatibility layer"
```
