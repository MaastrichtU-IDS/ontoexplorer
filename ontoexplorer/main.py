from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ontoexplorer.api.api_keys import router as api_keys_router
from ontoexplorer.api.auth import router as auth_router
from ontoexplorer.api.health import router as health_router
from ontoexplorer.api.jobs import router as jobs_router
from ontoexplorer.api.ontologies import router as ontologies_router
from ontoexplorer.api.sparql import router as sparql_router
from ontoexplorer.api.stats import router as stats_router
from ontoexplorer.api.webhooks import router as webhooks_router
from ontoexplorer.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        description="Next-generation FAIR ontology repository",
        version="0.1.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    if settings.enable_metrics:
        from prometheus_fastapi_instrumentator import Instrumentator
        Instrumentator().instrument(app).expose(app, endpoint="/metrics")

    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(sparql_router)
    app.include_router(jobs_router)
    app.include_router(ontologies_router)
    app.include_router(webhooks_router)
    app.include_router(api_keys_router)
    app.include_router(stats_router)

    return app


app = create_app()
