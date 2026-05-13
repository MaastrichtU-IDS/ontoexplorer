"""Tests for ontology auto-sync: polling and GitHub inbound webhook."""
import pytest
from ontoexplorer.models.db import Ontology, OntologyVersion


@pytest.mark.anyio
async def test_ontology_has_auto_sync_field(db_session):
    """Ontology model has auto_sync defaulting to False."""
    ont = Ontology(iri="http://example.org/sync-test.owl")
    db_session.add(ont)
    await db_session.commit()
    await db_session.refresh(ont)
    assert ont.auto_sync is False


@pytest.mark.anyio
async def test_version_has_source_url_field(db_session):
    """OntologyVersion model has source_url defaulting to None."""
    ont = Ontology(iri="http://example.org/sync-test2.owl")
    db_session.add(ont)
    await db_session.flush()
    ver = OntologyVersion(
        ontology_id=ont.id,
        minio_key="test/key.ttl",
        sha256="abc123unique",
        format="turtle",
        status="ready",
        source_url="https://raw.githubusercontent.com/owner/repo/main/onto.ttl",
    )
    db_session.add(ver)
    await db_session.commit()
    await db_session.refresh(ver)
    assert ver.source_url == "https://raw.githubusercontent.com/owner/repo/main/onto.ttl"


@pytest.mark.anyio
async def test_ingestion_stores_source_url(db_session):
    """run_ingestion sets source_url on the created OntologyVersion."""
    from unittest.mock import AsyncMock, MagicMock, patch
    from ontoexplorer.modules.ingestion.pipeline import IngestionRequest, run_ingestion
    from ontoexplorer.modules.ingestion.source_resolver import ResolvedSource, SourceMode

    _TURTLE = b"""
@prefix owl: <http://www.w3.org/2002/07/owl#> .
<http://example.org/SrcUrlOntology> a owl:Ontology .
"""
    _SOURCE_URL = "https://raw.githubusercontent.com/owner/repo/main/onto.ttl"

    mock_source = ResolvedSource(
        data=_TURTLE,
        content_type="text/turtle",
        final_url=_SOURCE_URL,
        mode=SourceMode.URL,
    )

    # Patch at the pipeline module level (where names are bound after import)
    with (
        patch("ontoexplorer.modules.ingestion.pipeline.resolve_url", return_value=mock_source),
        patch("ontoexplorer.modules.ingestion.pipeline.store_ontology",
              MagicMock(return_value="ont/ver/sha.ttl")),
        patch("ontoexplorer.modules.ingestion.pipeline.bulk_load_bytes",
              MagicMock(return_value=3)),
        patch("ontoexplorer.modules.ingestion.pipeline.resolve_imports_sparql",
              MagicMock(return_value={})),
        patch("ontoexplorer.modules.ingestion.pipeline._extract_ontology_iri_sparql",
              MagicMock(return_value=None)),
        patch("ontoexplorer.modules.ingestion.pipeline._extract_version_iri_sparql",
              MagicMock(return_value=None)),
        patch("ontoexplorer.modules.ingestion.pipeline._write_fair_metadata", new=AsyncMock()),
        patch("ontoexplorer.modules.jobs.tasks.reason_ontology",
              MagicMock(delay=MagicMock()), create=True),
        patch("ontoexplorer.modules.jobs.tasks.index_ontology",
              MagicMock(delay=MagicMock()), create=True),
    ):
        result = await run_ingestion(
            db_session,
            IngestionRequest(url=_SOURCE_URL),
        )

    from sqlalchemy import select
    ver_row = await db_session.execute(
        select(OntologyVersion).where(OntologyVersion.id == result.version_id)
    )
    ver = ver_row.scalar_one()
    assert ver.source_url == _SOURCE_URL


@pytest.mark.anyio
async def test_patch_auto_sync_on(client, user_and_key, db_session):
    """PATCH /ontologies/{id} sets auto_sync=True for the owner."""
    user, raw_key = user_and_key
    auth = {"Authorization": f"Bearer {raw_key}"}

    ont = Ontology(iri="http://example.org/patch-test.owl")
    db_session.add(ont)
    await db_session.commit()

    resp = await client.patch(
        f"/api/v1/ontologies/{ont.id}",
        json={"auto_sync": True},
        headers=auth,
    )
    assert resp.status_code == 200
    assert resp.json()["auto_sync"] is True

    await db_session.refresh(ont)
    assert ont.auto_sync is True


@pytest.mark.anyio
async def test_patch_auto_sync_wrong_user(client, db_session):
    """PATCH by a different user returns 403."""
    import hashlib
    import uuid as _uuid
    from ontoexplorer.models.db import ApiKey, User

    other_user = User(id=str(_uuid.uuid4()), email="other@example.com")
    raw_key2 = f"oe_test_{_uuid.uuid4().hex}"
    key_hash2 = hashlib.sha256(raw_key2.encode()).hexdigest()
    api_key2 = ApiKey(id=str(_uuid.uuid4()), user_id=other_user.id,
                      key_hash=key_hash2, name="k2", scopes=["read", "write"])
    ont = Ontology(iri="http://example.org/other-owner.owl", owner_id="some-other-id")
    db_session.add_all([other_user, api_key2, ont])
    await db_session.commit()

    resp = await client.patch(
        f"/api/v1/ontologies/{ont.id}",
        json={"auto_sync": True},
        headers={"Authorization": f"Bearer {raw_key2}"},
    )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_poll_queues_ingest_when_content_changes(db_session):
    """poll_for_updates queues ingest when fetched SHA-256 differs from stored."""
    from sqlalchemy import update as _update
    from unittest.mock import MagicMock, patch
    from ontoexplorer.modules.jobs.tasks import _run_poll

    # Disable auto_sync on all prior ontologies to isolate this test
    await db_session.execute(_update(Ontology).values(auto_sync=False))
    await db_session.flush()

    _NEW_CONTENT = b"new-content-bytes"
    _OLD_SHA256 = "aaaa1111"

    ont = Ontology(iri="http://example.org/poll-test.owl", auto_sync=True)
    db_session.add(ont)
    await db_session.flush()
    ver = OntologyVersion(
        ontology_id=ont.id,
        minio_key="test/key.ttl",
        sha256=_OLD_SHA256,
        format="turtle",
        status="ready",
        source_url="https://raw.githubusercontent.com/owner/repo/main/onto.ttl",
    )
    db_session.add(ver)
    await db_session.commit()

    mock_ingest = MagicMock()
    mock_ingest.delay = MagicMock()

    mock_resp = MagicMock()
    mock_resp.content = _NEW_CONTENT
    mock_resp.raise_for_status = MagicMock()

    with (
        patch("ontoexplorer.modules.jobs.tasks.ingest_ontology", mock_ingest),
        patch("httpx.Client") as mock_client_cls,
    ):
        mock_client_cls.return_value.__enter__.return_value.get.return_value = mock_resp
        await _run_poll(db_session)

    mock_ingest.delay.assert_called_once_with(
        url="https://raw.githubusercontent.com/owner/repo/main/onto.ttl",
        owner_id=None,
    )


@pytest.mark.anyio
async def test_poll_skips_when_content_unchanged(db_session):
    """poll_for_updates does NOT queue ingest when SHA-256 matches."""
    import hashlib
    from sqlalchemy import update as _update
    from unittest.mock import MagicMock, patch
    from ontoexplorer.modules.jobs.tasks import _run_poll

    # Disable auto_sync on all prior ontologies to isolate this test
    await db_session.execute(_update(Ontology).values(auto_sync=False))
    await db_session.flush()

    _CONTENT = b"unchanged-content"
    _SHA256 = hashlib.sha256(_CONTENT).hexdigest()

    ont = Ontology(iri="http://example.org/poll-noop.owl", auto_sync=True)
    db_session.add(ont)
    await db_session.flush()
    ver = OntologyVersion(
        ontology_id=ont.id,
        minio_key="test/key2.ttl",
        sha256=_SHA256,
        format="turtle",
        status="ready",
        source_url="https://raw.githubusercontent.com/owner/repo/main/onto2.ttl",
    )
    db_session.add(ver)
    await db_session.commit()

    mock_ingest = MagicMock()
    mock_ingest.delay = MagicMock()

    mock_resp = MagicMock()
    mock_resp.content = _CONTENT
    mock_resp.raise_for_status = MagicMock()

    with (
        patch("ontoexplorer.modules.jobs.tasks.ingest_ontology", mock_ingest),
        patch("httpx.Client") as mock_client_cls,
    ):
        mock_client_cls.return_value.__enter__.return_value.get.return_value = mock_resp
        await _run_poll(db_session)

    mock_ingest.delay.assert_not_called()


import hashlib as _hashlib
import hmac as _hmac
import json as _json


def _gh_sig(secret: str, body: bytes) -> str:
    return "sha256=" + _hmac.new(secret.encode(), body, _hashlib.sha256).hexdigest()


@pytest.mark.anyio
async def test_github_inbound_queues_ingest(client, db_session):
    """Valid GitHub push event queues ingest for matching source_url."""
    from unittest.mock import MagicMock, patch

    ont = Ontology(iri="http://example.org/gh-sync.owl")
    db_session.add(ont)
    await db_session.flush()
    ver = OntologyVersion(
        ontology_id=ont.id,
        minio_key="test/gh.ttl",
        sha256="deadbeef",
        format="turtle",
        status="ready",
        source_url="https://raw.githubusercontent.com/owner/repo/main/ontology.owl",
    )
    db_session.add(ver)
    await db_session.commit()

    payload = {
        "ref": "refs/heads/main",
        "repository": {"full_name": "owner/repo"},
        "commits": [{"added": [], "modified": ["ontology.owl"], "removed": []}],
    }
    body = _json.dumps(payload).encode()
    secret = "test-gh-secret"
    sig = _gh_sig(secret, body)

    mock_ingest = MagicMock()
    mock_ingest.delay = MagicMock()

    with (
        patch("ontoexplorer.api.inbound.get_settings",
              return_value=MagicMock(github_webhook_secret=secret)),
        patch("ontoexplorer.api.inbound.ingest_ontology", mock_ingest),
    ):
        resp = await client.post(
            "/api/v1/inbound/github",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-GitHub-Event": "push",
                "X-Hub-Signature-256": sig,
            },
        )

    assert resp.status_code == 200
    result = resp.json()
    assert result["queued"] == 1
    mock_ingest.delay.assert_called_once_with(
        url="https://raw.githubusercontent.com/owner/repo/main/ontology.owl"
    )


@pytest.mark.anyio
async def test_github_inbound_rejects_bad_signature(client):
    """Invalid HMAC signature returns 401."""
    from unittest.mock import MagicMock, patch

    body = b'{"ref": "refs/heads/main"}'
    with patch("ontoexplorer.api.inbound.get_settings",
               return_value=MagicMock(github_webhook_secret="real-secret")):
        resp = await client.post(
            "/api/v1/inbound/github",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-GitHub-Event": "push",
                "X-Hub-Signature-256": "sha256=badhex",
            },
        )
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_github_inbound_ignores_non_push_events(client):
    """Non-push events return 200 with queued=0 without error."""
    from unittest.mock import MagicMock, patch

    body = b'{}'
    secret = "test-secret"
    sig = _gh_sig(secret, body)

    with patch("ontoexplorer.api.inbound.get_settings",
               return_value=MagicMock(github_webhook_secret=secret)):
        resp = await client.post(
            "/api/v1/inbound/github",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-GitHub-Event": "pull_request",
                "X-Hub-Signature-256": sig,
            },
        )
    assert resp.status_code == 200
    assert resp.json()["queued"] == 0


@pytest.mark.anyio
async def test_github_inbound_no_secret_configured(client):
    """Returns 501 when GITHUB_WEBHOOK_SECRET is not configured."""
    from unittest.mock import MagicMock, patch

    body = b'{}'
    with patch("ontoexplorer.api.inbound.get_settings",
               return_value=MagicMock(github_webhook_secret="")):
        resp = await client.post(
            "/api/v1/inbound/github",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-GitHub-Event": "push",
                "X-Hub-Signature-256": "sha256=anything",
            },
        )
    assert resp.status_code == 501
