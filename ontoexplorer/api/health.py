
import httpx
from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from sqlalchemy import text

from ontoexplorer import __version__
from ontoexplorer.config import get_settings
from ontoexplorer.database import AsyncSessionLocal

router = APIRouter(tags=["health"])


@router.get("/health", summary="Liveness probe")
async def health():
    return {"status": "ok"}


@router.get("/api/v1/version", summary="Build version — app version + git ref/sha")
async def version():
    """The running build's version. `git_ref`/`git_sha` are injected at image
    build time (CI); both are null for a local/dev build, where `version` (the
    packaged __version__) is the source of truth."""
    s = get_settings()
    return {
        "version": __version__,
        "git_ref": s.git_ref or None,
        "git_sha": s.git_sha[:12] if s.git_sha else None,
    }


@router.get("/ready", summary="Readiness probe — checks all backend connections")
async def ready():
    settings = get_settings()
    checks: dict[str, str] = {}
    healthy = True

    # Postgres
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as exc:
        checks["postgres"] = f"error: {exc}"
        healthy = False

    # Fuseki
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{settings.fuseki_endpoint}{settings.fuseki_sparql_path}", params={"query": "SELECT * WHERE { ?s ?p ?o } LIMIT 1"})
            checks["fuseki"] = "ok" if resp.status_code < 500 else f"error: {resp.status_code}"
            if resp.status_code >= 500:
                healthy = False
    except Exception as exc:
        checks["fuseki"] = f"error: {exc}"
        healthy = False

    # MinIO (check if endpoint is reachable)
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            scheme = "https" if settings.minio_secure else "http"
            resp = await client.get(f"{scheme}://{settings.minio_endpoint}/minio/health/live")
            checks["minio"] = "ok" if resp.status_code == 200 else f"error: {resp.status_code}"
            if resp.status_code != 200:
                healthy = False
    except Exception as exc:
        checks["minio"] = f"error: {exc}"
        healthy = False

    # ELK reasoning service
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{settings.reasoner_service_url}/health")
            checks["elk"] = "ok" if resp.status_code == 200 else f"error: {resp.status_code}"
            if resp.status_code != 200:
                healthy = False
    except Exception as exc:
        checks["elk"] = f"error: {exc}"
        # ELK unavailable is degraded but not fatal for read operations
        healthy = False

    code = status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse({"status": "ready" if healthy else "degraded", "checks": checks}, status_code=code)
