"""Inbound webhook receivers — GitHub push events."""

import hashlib
import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ontoexplorer.config import get_settings
from ontoexplorer.database import get_db
from ontoexplorer.models.db import Ontology, OntologyVersion
from ontoexplorer.modules.jobs.tasks import ingest_ontology
from ontoexplorer.logging_config import get_logger

router = APIRouter(prefix="/api/v1/inbound", tags=["inbound"])
log = get_logger(__name__)


def _verify_github_signature(secret: str, body: bytes, signature_header: str) -> bool:
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)


@router.post("/github", summary="Receive GitHub push webhook")
async def github_webhook(
    request: Request,
    x_github_event: str = Header(default=""),
    x_hub_signature_256: str = Header(default=""),
    db: AsyncSession = Depends(get_db),
):
    settings = get_settings()
    if not settings.github_webhook_secret:
        raise HTTPException(status_code=501, detail="GITHUB_WEBHOOK_SECRET not configured")

    body = await request.body()
    if not _verify_github_signature(settings.github_webhook_secret, body, x_hub_signature_256):
        raise HTTPException(status_code=401, detail="Invalid signature")

    if x_github_event != "push":
        return {"queued": 0, "detail": f"Ignoring event: {x_github_event}"}

    payload = await request.json()
    ref = payload.get("ref", "")
    repo_full_name = payload.get("repository", {}).get("full_name", "")
    if not ref or not repo_full_name:
        return {"queued": 0}

    # Extract branch or tag name from refs/heads/main or refs/tags/v1.0
    ref_parts = ref.split("/", 2)
    ref_name = ref_parts[2] if len(ref_parts) == 3 else ref_parts[-1]

    # Collect all changed/added file paths
    changed_paths: set[str] = set()
    for commit in payload.get("commits", []):
        changed_paths.update(commit.get("added", []))
        changed_paths.update(commit.get("modified", []))

    if not changed_paths:
        return {"queued": 0}

    # Build raw GitHub URLs for each changed path
    candidate_urls = [
        f"https://raw.githubusercontent.com/{repo_full_name}/{ref_name}/{path}"
        for path in changed_paths
    ]

    # Find registered ontologies whose source_url matches a changed file, and
    # carry the owner + groups into the re-ingest. Without owner_id the ingest
    # task defaults it to None; that is harmless while the ontology's IRI still
    # matches an existing row (the pipeline preserves the owner then), but if the
    # upstream file's ontology IRI has changed it lands in the create branch and
    # would mint an *ownerless* ontology. The scheduled poller already passes
    # owner_id; this keeps the two sync paths in step.
    result = await db.execute(
        select(OntologyVersion.source_url, Ontology.owner_id, Ontology.groups)
        .join(Ontology, OntologyVersion.ontology_id == Ontology.id)
        .where(OntologyVersion.source_url.in_(candidate_urls))
        .where(OntologyVersion.status != "deprecated")
    )
    # One entry per source_url (a URL maps to a single ontology; dedupe the
    # multiple versions that can share it).
    matched: dict[str, tuple[str | None, list]] = {}
    for source_url, owner_id, groups in result.all():
        matched.setdefault(source_url, (owner_id, list(groups or [])))

    for url, (owner_id, groups) in matched.items():
        ingest_ontology.delay(url=url, owner_id=owner_id, groups=groups)
        log.info("github_sync_queued", url=url, repo=repo_full_name, ref=ref)

    return {"queued": len(matched), "urls": list(matched)}
