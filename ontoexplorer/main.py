from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import structlog

from ontoexplorer import __version__

from ontoexplorer.api.api_keys import router as api_keys_router
from ontoexplorer.api.maintainers import admin_router as maintainer_admin_router
from ontoexplorer.api.maintainers import router as maintainer_router
from ontoexplorer.api.global_search import router as global_search_router
from ontoexplorer.api.auth import router as auth_router
from ontoexplorer.api.health import router as health_router
from ontoexplorer.api.jobs import router as jobs_router
from ontoexplorer.api.ontologies import router as ontologies_router, reasoners_router
from ontoexplorer.api.reasoner_profiles import router as reasoner_profiles_router
from ontoexplorer.api.search import router as search_router
from ontoexplorer.api.sparql import router as sparql_router
from ontoexplorer.api.sparql_queries import router as sparql_queries_router, starters_router as sparql_starters_router
from ontoexplorer.api.admin import router as admin_router
from ontoexplorer.api.stats import router as stats_router
from ontoexplorer.api.inbound import router as inbound_router
from ontoexplorer.api.webhooks import router as webhooks_router
from ontoexplorer.api.profile import router as profile_router
from ontoexplorer.api.meta_profile import router as meta_profile_router
from ontoexplorer.api.diff import router as diff_router
from ontoexplorer.api.mod import router as mod_router
from ontoexplorer.api.compare import router as compare_router
from ontoexplorer.api.coverage import router as coverage_router
from ontoexplorer.api.owl_profile import router as owl_profile_router
from ontoexplorer.api.reuse import router as reuse_router
from ontoexplorer.api.ols import router as ols_router
from ontoexplorer.config import get_settings
from ontoexplorer.logging_config import configure_logging


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(log_level=settings.log_level, json_logs=settings.json_logs)
    log = structlog.get_logger("ontoexplorer.startup")

    app = FastAPI(
        title=settings.app_name,
        description="Next-generation FAIR ontology repository",
        version=__version__,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,  # credentials require explicit origin list, not wildcard
        allow_methods=["*"],
        allow_headers=["*"],
    )

    if settings.enable_metrics:
        from prometheus_fastapi_instrumentator import Instrumentator
        Instrumentator().instrument(app).expose(app, endpoint="/metrics")

    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(sparql_router)
    app.include_router(sparql_queries_router)
    app.include_router(sparql_starters_router)
    app.include_router(jobs_router)
    # global_search_router before ontologies_router: static /search segment must match
    # before ontologies_router's /{ontology_id}/{version_id} parameterized route
    app.include_router(global_search_router)
    # meta_profile_router before profile_router and ontologies_router: static /meta
    # segments must match before ontologies_router's parameterized sub-routes
    app.include_router(meta_profile_router)
    # profile_router before ontologies_router: /profile and /profile/candidates static
    # segments must match before ontologies_router's parameterized sub-routes
    app.include_router(profile_router)
    # diff_router before ontologies_router: /{id}/diff static segment must
    # take precedence over ontologies_router's /{id}/{version_id} parameter
    app.include_router(diff_router)
    app.include_router(compare_router)
    # coverage_router before ontologies_router: /{id}/{vid}/coverage static segment must
    # match before ontologies_router's parameterized sub-routes
    app.include_router(coverage_router)
    # owl_profile_router before ontologies_router: /{id}/{vid}/owl-profile static segment must
    # match before ontologies_router's parameterized sub-routes
    app.include_router(owl_profile_router)
    # reuse_router before ontologies_router: /{id}/{vid}/reuse static segment must
    # match before ontologies_router's parameterized sub-routes
    app.include_router(reuse_router)
    app.include_router(ontologies_router)
    app.include_router(reasoners_router)
    app.include_router(reasoner_profiles_router)
    # The incremental reasoning API is deprecated and no longer served. Its UI
    # was removed in 0.3.82, and live testing showed any authenticated account
    # could open a session against any ontology — each one holding a persistent
    # `km` subprocess. Registration is open, so that was a resource commitment
    # any stranger could make. Sessions were sandboxed (an in-memory
    # pyoxigraph.Store, never the stored graph), so nothing was exposed; the
    # exposure was capacity.
    #
    # api/incremental.py and the reasoner-service backend are left in place. To
    # bring it back, decide who may open a session and what bounds a session
    # before re-registering the router.
    app.include_router(search_router)
    app.include_router(webhooks_router)
    app.include_router(inbound_router)
    app.include_router(api_keys_router)
    app.include_router(maintainer_router)
    app.include_router(maintainer_admin_router)
    app.include_router(stats_router)
    app.include_router(admin_router)
    app.include_router(mod_router)
    app.include_router(ols_router)

    # Production safety latch — refuse to boot when ENVIRONMENT=production
    # and any insecure default is still in place.
    problems = settings.validate_production()
    if problems:
        for p in problems:
            log.error("startup_blocked", reason=p)
        raise RuntimeError(
            "Refusing to start in production with insecure defaults: "
            + " | ".join(problems)
        )
    # Outside of production, surface the same checks as warnings so devs
    # see them before deploying.
    if settings.jwt_secret_key == "change-me-in-production":
        log.warning("SECURITY: jwt_secret_key is the default value — set JWT_SECRET_KEY before going to production")
    if settings.auth_bypass:
        log.warning("SECURITY: auth_bypass=true — every request is silently dev@localhost (do not ship)")

    @app.on_event("startup")
    async def _warm_embedder() -> None:
        # Load the semantic-search embedding model per worker at boot, off the
        # request path. Without this the model cold-loads on the first semantic
        # query each of the (workers x replicas) processes handles — the erratic
        # multi-second spikes on the home search. Background thread so startup /
        # readiness isn't blocked.
        import threading

        def _warm() -> None:
            try:
                from ontoexplorer.modules.search.embedder import embed_query
                embed_query("warmup")
                log.info("embedder warmed")
            except Exception as e:  # never let warmup failure affect serving
                log.warning("embedder warmup failed", error=str(e))

        threading.Thread(target=_warm, name="embedder-warmup", daemon=True).start()

    log.info("OntoExplorer API ready", version=__version__, environment=settings.environment)
    return app


app = create_app()
