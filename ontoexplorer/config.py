from functools import lru_cache

from pydantic import AliasChoices, AnyHttpUrl, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Application
    app_name: str = "OntoExplorer"
    app_url: AnyHttpUrl = "http://localhost:8000"  # type: ignore[assignment]
    frontend_url: str = "http://localhost:5173"
    debug: bool = False
    # Deployment environment. Settings.validate_production() refuses to boot
    # when this is "production" and any insecure default is still in place
    # (JWT key, AUTH_BYPASS, etc.). Accepted values:
    #   development | staging | production
    environment: str = "development"

    # Build provenance — injected at Docker build time from CI (git ref + sha).
    # Empty in local/dev; the /api/v1/version endpoint then falls back to the
    # packaged __version__ for the ref.
    git_ref: str = ""
    git_sha: str = ""

    # Postgres
    database_url: str = "postgresql+asyncpg://ontoexplorer:ontoexplorer@localhost:5432/ontoexplorer"

    # Redis / Celery
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    # MinIO
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_secure: bool = False
    minio_ontologies_bucket: str = "ontologies"
    minio_imports_bucket: str = "imports"
    # Staging area for file uploads: the API streams the upload here and passes
    # only the object key to the ingest task, instead of shipping the bytes
    # (hex-encoded, ~2x) through the Celery/Redis broker.
    minio_uploads_bucket: str = "uploads"
    # Periodic snapshots of processed aggregates (e.g. usage_daily) live here so
    # the stats survive a bad migration / accidental drop / postgres-PVC loss.
    minio_backups_bucket: str = "backups"
    # Pinned so the client never issues a live GET /{bucket}?location= to
    # discover it. That probe is pure latency on every signing path, and when it
    # ran against an endpoint the cluster could not reach it failed outright.
    minio_region: str = "us-east-1"

    # Oxigraph (embedded content triplestore) — path to data directory
    oxigraph_data_path: str = "/data/oxigraph"
    oxigraph_read_only: bool = False  # set True in API container; worker keeps write access

    # Metadata triplestore (embedded pyoxigraph, replaced Jena Fuseki) — a
    # separate store from the content one; serves /sparql. Same RW/RO model as
    # oxigraph (governed by oxigraph_read_only: worker RW, API RO secondary).
    metadata_store_path: str = "/data/metadata"

    sparql_query_timeout_seconds: int = 30

    # Reasoning service (currently runs whelk; ELK_SERVICE_* kept as deprecated aliases)
    reasoner_service_url: str = Field(
        default="http://localhost:8001",
        validation_alias=AliasChoices("REASONER_SERVICE_URL", "ELK_SERVICE_URL"),
    )
    reasoner_service_timeout: int = Field(
        default=3600,  # seconds — large ontologies (GO) can take >10 min
        validation_alias=AliasChoices("REASONER_SERVICE_TIMEOUT", "ELK_SERVICE_TIMEOUT"),
    )
    # Reasoner selected for an ontology when the ingest request omits one.
    default_reasoner: str = "rustdl"

    # Anthropic
    anthropic_api_key: str = ""

    # Secret for the rotating daily salt used to dedup usage views/downloads.
    # Falls back to jwt_secret_key when unset. Never stored per-visitor.
    usage_hash_salt: str = ""

    # JWT / session
    jwt_secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60
    jwt_refresh_token_expire_days: int = 30

    # OAuth — ORCID
    orcid_client_id: str = ""
    orcid_client_secret: str = ""
    orcid_sandbox: bool = False  # True → use sandbox.orcid.org

    # OAuth — GitHub
    github_client_id: str = ""
    github_client_secret: str = ""

    # OAuth — Google
    google_client_id: str = ""
    google_client_secret: str = ""

    # Inbound GitHub webhook — set to the secret configured in the GitHub repo's webhook settings
    github_webhook_secret: str = ""

    # Admin access — comma-separated list of email addresses granted /admin access
    admin_emails: str = ""
    # Ontology upload allowlist — comma-separated emails permitted to add
    # ontologies (in ADDITION to admins). Empty => admins only.
    upload_allowed_emails: str = ""

    # Development auth bypass — set AUTH_BYPASS=true to skip OAuth for local dev
    auth_bypass: bool = False

    # Prometheus
    enable_metrics: bool = True

    # Logging
    log_level: str = "INFO"
    json_logs: bool = True

    # Ingestion — hard ceiling on a fetched ontology source (IRI/URL download).
    # Enforced while streaming, so an oversized source is abandoned mid-transfer
    # rather than buffered in full. Sized to admit the largest OBO ontologies
    # (DRON is ~674 MiB and growing); raise via INGEST_MAX_SOURCE_BYTES.
    ingest_max_source_bytes: int = 2 * 1024 * 1024 * 1024  # 2 GiB

    # Ingestion SSRF guard. By default every outbound ontology fetch (source
    # URL/IRI and owl:imports) must resolve to a public address; loopback,
    # link-local (incl. cloud metadata), private and reserved ranges are
    # refused, on the original request and on every redirect hop. Local
    # development that legitimately fetches localhost imports sets
    # INGEST_ALLOW_PRIVATE_FETCH=true, or names specific hosts in
    # INGEST_FETCH_ALLOW_HOSTS (comma-separated).
    ingest_allow_private_fetch: bool = False
    ingest_fetch_allow_hosts: str = ""

    # MOD-API
    mod_catalogue_title: str = "OntoExplorer Catalogue"
    mod_catalogue_description: str = "A FAIR ontology repository"
    mod_rate_limit_anon: int = 1000   # requests / day — unauthenticated (per IP)
    mod_rate_limit_auth: int = 10000  # requests / day — authenticated (per API key)

    # Justification is session-only and cheap to request but dispatches an OWL
    # justification job with an 11-minute hard limit on the reasoner pool, so a
    # burst of requests can starve reasoning for everyone. Two per-user limits:
    # how many may run at once (burst protection — the real resource is
    # simultaneous long jobs), and how many per day (sustained-abuse ceiling).
    justification_max_inflight: int = 2
    justification_daily_limit: int = 200

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        if not v.startswith("postgresql"):
            raise ValueError("database_url must be a PostgreSQL URL")
        return v

    def validate_production(self) -> list[str]:
        """Return a list of human-readable failure reasons when running in
        production with insecure defaults. Empty list = safe to boot.

        Called once at app startup; if any failure is reported, the process
        refuses to start instead of silently shipping with the default JWT
        secret or auth bypass enabled.
        """
        if self.environment != "production":
            return []
        problems: list[str] = []
        if self.jwt_secret_key == "change-me-in-production":
            problems.append(
                "JWT_SECRET_KEY is the placeholder default — set a long random "
                "value in the environment before booting in production."
            )
        if self.auth_bypass:
            problems.append(
                "AUTH_BYPASS=true is incompatible with ENVIRONMENT=production "
                "(every request would silently be treated as the dev user)."
            )
        return problems


def is_admin(user) -> bool:
    """Return True if user.email is in the ADMIN_EMAILS allowlist."""
    emails = {e.strip().lower() for e in get_settings().admin_emails.split(",") if e.strip()}
    return bool(user.email and user.email.lower() in emails)


def can_upload(user) -> bool:
    """Return True if the user may add ontologies: admins always; users granted
    the uploader role (is_uploader, via an approved maintainer request); plus any
    email in the UPLOAD_ALLOWED_EMAILS allowlist. Empty allowlist => admins only."""
    if is_admin(user):
        return True
    if getattr(user, "is_uploader", False):
        return True
    emails = {e.strip().lower() for e in get_settings().upload_allowed_emails.split(",") if e.strip()}
    return bool(user.email and user.email.lower() in emails)


@lru_cache
def get_settings() -> Settings:
    return Settings()
