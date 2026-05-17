from pydantic import AnyHttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Application
    app_name: str = "OntoExplorer"
    app_url: AnyHttpUrl = "http://localhost:8000"  # type: ignore[assignment]
    frontend_url: str = "http://localhost:5173"
    debug: bool = False

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

    # SPARQL metadata store (Fuseki)
    qlever_endpoint: str = "http://localhost:7001"
    qlever_sparql_path: str = "/sparql"
    qlever_update_user: str = ""
    qlever_update_password: str = ""

    # Oxigraph (embedded content triplestore) — path to data directory
    oxigraph_data_path: str = "/data/oxigraph"
    oxigraph_read_only: bool = False  # set True in API container; worker keeps write access

    # Oxigraph SPARQL server (isolated read-only container)
    oxigraph_sparql_url: str = "http://oxigraph-sparql:7878"
    sparql_query_timeout_seconds: int = 30

    # ELK reasoning service
    elk_service_url: str = "http://localhost:8001"
    elk_service_timeout: int = 3600  # seconds — large ontologies (GO) can take >10 min

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
    mod_rate_limit_anon: int = 1000
    mod_rate_limit_auth: int = 10000

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        if not v.startswith("postgresql"):
            raise ValueError("database_url must be a PostgreSQL URL")
        return v


def is_admin(user) -> bool:
    """Return True if user.email is in the ADMIN_EMAILS allowlist."""
    emails = {e.strip().lower() for e in get_settings().admin_emails.split(",") if e.strip()}
    return bool(user.email and user.email.lower() in emails)


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
