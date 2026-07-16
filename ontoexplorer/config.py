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
    # Public-facing endpoint used only for presigned URL generation.
    # Defaults to minio_endpoint so local dev works without extra config.
    # In prod set to the externally reachable hostname (e.g. minio.example.com).
    minio_public_endpoint: str = ""
    minio_public_secure: bool = False

    # SPARQL metadata store (Jena Fuseki)
    fuseki_endpoint: str = "http://localhost:7001"
    fuseki_sparql_path: str = "/sparql"
    fuseki_update_user: str = ""
    fuseki_update_password: str = ""

    # Oxigraph (embedded content triplestore) — path to data directory
    oxigraph_data_path: str = "/data/oxigraph"
    oxigraph_read_only: bool = False  # set True in API container; worker keeps write access

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

    # Anthropic
    anthropic_api_key: str = ""

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

    # Development auth bypass — set AUTH_BYPASS=true to skip OAuth for local dev
    auth_bypass: bool = False

    # Prometheus
    enable_metrics: bool = True

    # Logging
    log_level: str = "INFO"
    json_logs: bool = True

    # MOD-API
    mod_catalogue_title: str = "OntoExplorer Catalogue"
    mod_catalogue_description: str = "A FAIR ontology repository"
    mod_rate_limit_anon: int = 1000   # requests / day — unauthenticated (per IP)
    mod_rate_limit_auth: int = 10000  # requests / day — authenticated (per API key)

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
