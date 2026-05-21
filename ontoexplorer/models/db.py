import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector

from ontoexplorer.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    email: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    display_name: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    preferred_lang: Mapped[str | None] = mapped_column(String, nullable=True)
    lang_fallback_strategy: Mapped[str] = mapped_column(String, nullable=False, default="silent", server_default="silent")

    oauth_accounts: Mapped[list["OAuthAccount"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    sessions: Mapped[list["Session"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    ontologies: Mapped[list["Ontology"]] = relationship(back_populates="owner")
    api_keys: Mapped[list["ApiKey"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    webhooks: Mapped[list["Webhook"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    saved_queries: Mapped[list["SavedQuery"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class OAuthAccount(Base):
    __tablename__ = "oauth_accounts"
    __table_args__ = (UniqueConstraint("provider", "provider_user_id"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String)  # "orcid" | "github" | "google"
    provider_user_id: Mapped[str] = mapped_column(String)
    access_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="oauth_accounts")


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String, unique=True)  # SHA-256 of refresh token
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="sessions")


class Ontology(Base):
    __tablename__ = "ontologies"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    iri: Mapped[str] = mapped_column(String, unique=True)
    shortname: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    title: Mapped[str | None] = mapped_column(String, nullable=True)

    def __init__(self, **kwargs):
        """Auto-derive shortname from IRI when not provided.

        The DB column is NOT NULL; callers that have no shortname in hand
        (typically tests) get a best-effort inference rather than a crash.
        For production ingest, callers should pass an explicit shortname
        produced by `unique_shortname` to avoid collisions.
        """
        if "shortname" not in kwargs or kwargs["shortname"] is None:
            from ontoexplorer.modules.ingestion.shortname import (
                infer_shortname_from_iri,
            )
            iri = kwargs.get("iri", "")
            inferred = infer_shortname_from_iri(iri)
            if inferred is None:
                # Synthesize a unique fallback so the NOT NULL + UNIQUE
                # constraints both hold even when called without an id.
                seed = kwargs.get("id") or _uuid()
                kwargs.setdefault("id", seed)
                inferred = f"ont-{seed[:8]}"
            kwargs["shortname"] = inferred
        super().__init__(**kwargs)

    groups: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    auto_sync: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    preferred_lang: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    owner: Mapped[User | None] = relationship(back_populates="ontologies")
    versions: Mapped[list["OntologyVersion"]] = relationship(back_populates="ontology", cascade="all, delete-orphan")


class OntologyVersion(Base):
    __tablename__ = "versions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    ontology_id: Mapped[str] = mapped_column(ForeignKey("ontologies.id", ondelete="CASCADE"))
    version_iri: Mapped[str | None] = mapped_column(String, nullable=True)
    minio_key: Mapped[str] = mapped_column(String)           # path in MinIO
    sha256: Mapped[str] = mapped_column(String, unique=True) # content hash for dedup
    format: Mapped[str] = mapped_column(String)              # "owl", "turtle", "obo", etc.
    status: Mapped[str] = mapped_column(String, default="ingested")  # ingested | reasoning | ready | deprecated
    source_url: Mapped[str | None] = mapped_column(String, nullable=True)
    triple_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    ontology: Mapped[Ontology] = relationship(back_populates="versions")
    imports: Mapped[list["OntologyImport"]] = relationship(back_populates="version", cascade="all, delete-orphan")
    jobs: Mapped[list["Job"]] = relationship(back_populates="version", passive_deletes=True)


class OntologyImport(Base):
    __tablename__ = "imports"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    version_id: Mapped[str] = mapped_column(ForeignKey("versions.id", ondelete="CASCADE"))
    import_iri: Mapped[str] = mapped_column(String)
    resolved_minio_key: Mapped[str | None] = mapped_column(String, nullable=True)  # None if fetch failed

    version: Mapped[OntologyVersion] = relationship(back_populates="imports")


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    version_id: Mapped[str] = mapped_column(ForeignKey("versions.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String)    # "reasoning" | "indexing"
    status: Mapped[str] = mapped_column(String, default="pending")  # pending | running | done | failed
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    version: Mapped[OntologyVersion] = relationship(back_populates="jobs", passive_deletes=True)


class Webhook(Base):
    __tablename__ = "webhooks"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    url: Mapped[str] = mapped_column(String)
    events: Mapped[list[str]] = mapped_column(JSON)  # ["ontology.ingested", ...]
    secret: Mapped[str | None] = mapped_column(String, nullable=True)  # HMAC signing secret
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship(back_populates="webhooks")
    deliveries: Mapped[list["WebhookDelivery"]] = relationship(back_populates="webhook", cascade="all, delete-orphan")


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    webhook_id: Mapped[str] = mapped_column(ForeignKey("webhooks.id", ondelete="CASCADE"))
    event: Mapped[str] = mapped_column(String)
    payload: Mapped[str] = mapped_column(Text)   # JSON string
    status: Mapped[str] = mapped_column(String, default="pending")  # pending | delivered | failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)

    webhook: Mapped[Webhook] = relationship(back_populates="deliveries")


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    key_hash: Mapped[str] = mapped_column(String, unique=True)  # SHA-256 of the raw key
    name: Mapped[str] = mapped_column(String)
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="api_keys")


class OntologyProfile(Base):
    __tablename__ = "ontology_profiles"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    version_id: Mapped[str] = mapped_column(
        ForeignKey("versions.id", ondelete="CASCADE"), unique=True
    )
    label_props: Mapped[list] = mapped_column(JSON, default=list)
    definition_props: Mapped[list] = mapped_column(JSON, default=list)
    synonym_props: Mapped[list] = mapped_column(JSON, default=list)
    deprecated_props: Mapped[list] = mapped_column(JSON, default=list)
    example_props: Mapped[list] = mapped_column(JSON, default=list)
    candidates_data: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String, default="auto_detected")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    version: Mapped["OntologyVersion"] = relationship(passive_deletes=True)


class OntologyMetaProfile(Base):
    __tablename__ = "ontology_meta_profiles"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    version_id: Mapped[str] = mapped_column(
        ForeignKey("versions.id", ondelete="CASCADE"), unique=True
    )
    title_props: Mapped[list] = mapped_column(JSON, default=list)
    shortname_props: Mapped[list] = mapped_column(JSON, default=list)
    description_props: Mapped[list] = mapped_column(JSON, default=list)
    creator_props: Mapped[list] = mapped_column(JSON, default=list)
    contributor_props: Mapped[list] = mapped_column(JSON, default=list)
    publisher_props: Mapped[list] = mapped_column(JSON, default=list)
    license_props: Mapped[list] = mapped_column(JSON, default=list)
    homepage_props: Mapped[list] = mapped_column(JSON, default=list)
    version_info_props: Mapped[list] = mapped_column(JSON, default=list)
    version_iri_props: Mapped[list] = mapped_column(JSON, default=list)
    prefix_props: Mapped[list] = mapped_column(JSON, default=list)
    namespace_uri_props: Mapped[list] = mapped_column(JSON, default=list)
    created_props: Mapped[list] = mapped_column(JSON, default=list)
    modified_props: Mapped[list] = mapped_column(JSON, default=list)
    language_props: Mapped[list] = mapped_column(JSON, default=list)
    citation_props: Mapped[list] = mapped_column(JSON, default=list)
    funding_props: Mapped[list] = mapped_column(JSON, default=list)
    status_props: Mapped[list] = mapped_column(JSON, default=list)
    syntax_props: Mapped[list] = mapped_column(JSON, default=list)
    see_also_props: Mapped[list] = mapped_column(JSON, default=list)
    is_defined_by_props: Mapped[list] = mapped_column(JSON, default=list)
    competency_question_props: Mapped[list] = mapped_column(JSON, default=list)
    endorsed_by_props: Mapped[list] = mapped_column(JSON, default=list)
    relies_on_props: Mapped[list] = mapped_column(JSON, default=list)
    similar_props: Mapped[list] = mapped_column(JSON, default=list)
    generalizes_props: Mapped[list] = mapped_column(JSON, default=list)
    specializes_props: Mapped[list] = mapped_column(JSON, default=list)
    known_usage_props: Mapped[list] = mapped_column(JSON, default=list)
    used_in_project_props: Mapped[list] = mapped_column(JSON, default=list)
    resolved: Mapped[dict] = mapped_column(JSON, default=dict)
    candidates_data: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String, default="auto_detected")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    version: Mapped["OntologyVersion"] = relationship(passive_deletes=True)


class OntologyDiff(Base):
    __tablename__ = "ontology_diffs"
    __table_args__ = (UniqueConstraint("version_from_id", "version_to_id"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    ontology_id: Mapped[str] = mapped_column(ForeignKey("ontologies.id", ondelete="CASCADE"))
    version_from_id: Mapped[str] = mapped_column(ForeignKey("versions.id", ondelete="CASCADE"))
    version_to_id: Mapped[str] = mapped_column(ForeignKey("versions.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String, default="pending")  # pending | ready | failed
    summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    diff_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    narrative: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OntologyComparison(Base):
    """Cross-ontology comparison between two version IDs from (possibly)
    different ontologies. Mirrors OntologyDiff but carries TWO ontology IDs.
    """
    __tablename__ = "ontology_comparisons"
    __table_args__ = (UniqueConstraint("version_from_id", "version_to_id"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    from_ontology_id: Mapped[str] = mapped_column(
        ForeignKey("ontologies.id", ondelete="CASCADE")
    )
    to_ontology_id: Mapped[str] = mapped_column(
        ForeignKey("ontologies.id", ondelete="CASCADE")
    )
    version_from_id: Mapped[str] = mapped_column(
        ForeignKey("versions.id", ondelete="CASCADE")
    )
    version_to_id: Mapped[str] = mapped_column(
        ForeignKey("versions.id", ondelete="CASCADE")
    )
    status: Mapped[str] = mapped_column(String, default="pending")  # pending | ready | failed
    summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    diff_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class TermEmbedding(Base):
    __tablename__ = "term_embeddings"
    __table_args__ = (UniqueConstraint("version_id", "entity_iri"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    version_id: Mapped[str] = mapped_column(ForeignKey("versions.id", ondelete="CASCADE"))
    entity_iri: Mapped[str] = mapped_column(Text)
    entity_type: Mapped[str] = mapped_column(String)
    text_hash: Mapped[str] = mapped_column(String)
    embedding: Mapped[list] = mapped_column(Vector(768))


class EntityIndex(Base):
    """Slim per-entity row mirrored from Redis so /search can run as one SQL query.

    Compound primary key (version_id, iri) — the same IRI appears in many ontologies.
    search_tsv is a generated tsvector covering primary label + all labels + synonyms
    so prefix/word-suffix matches behave like the Redis-side sorted-set index.
    """
    __tablename__ = "entity_index"

    version_id: Mapped[str] = mapped_column(ForeignKey("versions.id", ondelete="CASCADE"), primary_key=True)
    iri: Mapped[str] = mapped_column(Text, primary_key=True)
    ontology_id: Mapped[str] = mapped_column(ForeignKey("ontologies.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String, nullable=False)
    primary_label: Mapped[str] = mapped_column(Text, nullable=False)
    primary_label_norm: Mapped[str] = mapped_column(Text, nullable=False)
    short: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    search_text: Mapped[str] = mapped_column(Text, nullable=False)
    # search_tsv is a generated column; SQLAlchemy reads it but never writes it.


class SavedQuery(Base):
    __tablename__ = "saved_queries"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)
    is_starter: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user: Mapped["User"] = relationship(back_populates="saved_queries")
