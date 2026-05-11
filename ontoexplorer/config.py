from pydantic import AnyHttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Application
    app_name: str = "OntoExplorer"
    app_url: AnyHttpUrl = "http://localhost:8000"  # type: ignore[assignment]
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

    # QLever (metadata SPARQL)
    qlever_endpoint: str = "http://localhost:7001"
    qlever_sparql_path: str = "/sparql"

    # Oxigraph (embedded content triplestore) — path to data directory
    oxigraph_data_path: str = "/data/oxigraph"
    oxigraph_read_only: bool = False  # set True in API container; worker keeps write access

    # ELK reasoning service
    elk_service_url: str = "http://localhost:8001"
    elk_service_timeout: int = 300  # seconds — reasoning can be slow

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

    # Prometheus
    enable_metrics: bool = True

    # Logging
    log_level: str = "INFO"
    json_logs: bool = True

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        if not v.startswith("postgresql"):
            raise ValueError("database_url must be a PostgreSQL URL")
        return v


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
