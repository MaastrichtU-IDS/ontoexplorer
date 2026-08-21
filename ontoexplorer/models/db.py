import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
)
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
    # Global grant: may add NEW ontologies (in addition to admins + the
    # UPLOAD_ALLOWED_EMAILS env allowlist). Set when an "uploader" maintainer
    # request is approved. See can_upload().
    is_uploader: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")

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
    # Admin-pinned default version. When set (and still ready), it overrides the
    # automatic version-aware "latest" selection. Nullable FK; SET NULL so
    # deleting the pinned version falls back to automatic selection.
    current_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("versions.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    owner: Mapped[User | None] = relationship(back_populates="ontologies")
    # `foreign_keys` is explicit because there are now two FKs between ontologies
    # and versions (versions.ontology_id and ontologies.current_version_id); this
    # relationship is the ontology_id one.
    versions: Mapped[list["OntologyVersion"]] = relationship(
        back_populates="ontology",
        cascade="all, delete-orphan",
        foreign_keys="OntologyVersion.ontology_id",
    )


class OntologyVersion(Base):
    __tablename__ = "versions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    ontology_id: Mapped[str] = mapped_column(ForeignKey("ontologies.id", ondelete="CASCADE"))
    version_iri: Mapped[str | None] = mapped_column(String, nullable=True)
    minio_key: Mapped[str] = mapped_column(String)           # path in MinIO
    sha256: Mapped[str] = mapped_column(String, unique=True) # content hash for dedup
    format: Mapped[str] = mapped_column(String)              # "owl", "turtle", "obo", etc.
    status: Mapped[str] = mapped_column(String, default="ingested")  # ingested | reasoning | ready | deprecated
    reasoner: Mapped[str] = mapped_column(String, nullable=False, server_default="rustdl")
    # Reference-binding to the reasoner profile chosen at add/reindex time; each
    # (re)reason resolves the profile's current params. `reasoner` stays the
    # denormalized effective backend name. Null = no profile (raw reasoner + auto).
    reasoner_profile_id: Mapped[str | None] = mapped_column(
        ForeignKey("reasoner_profiles.id", ondelete="SET NULL"), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String, nullable=True)
    triple_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    ontology: Mapped[Ontology] = relationship(
        back_populates="versions", foreign_keys="OntologyVersion.ontology_id")
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
    # Nullable: an "ingestion" job is created from the Celery task id before any
    # version exists, so a submission that fails early (unreachable IRI,
    # oversized source, unparseable file) still leaves a queryable row. Filled
    # in once ingestion produces a version.
    version_id: Mapped[str | None] = mapped_column(
        ForeignKey("versions.id", ondelete="CASCADE"), nullable=True
    )
    type: Mapped[str] = mapped_column(String)    # "ingestion" | "reason" | "indexing" | ...
    status: Mapped[str] = mapped_column(String, default="pending")  # pending | running | done | failed
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Provenance for reasoning runs: the effective {reasoner, params, profile_id}
    # actually used (reference-binding resolves params at run time, so we snapshot).
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    version: Mapped[OntologyVersion | None] = relationship(back_populates="jobs", passive_deletes=True)


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
    elucidation_props: Mapped[list] = mapped_column(JSON, default=list)
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
    # Mirrored from the indexer's deprecated set so the SQL-backed navigation
    # tree can honour hide_obsolete without consulting Redis or Oxigraph.
    deprecated: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())
    # No parent in its own hierarchy. Precomputed at index time: as a query-time
    # anti-join this is a LIMIT trap the planner loses badly (26 s on DRON).
    is_root: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())
    # search_tsv is a generated column; SQLAlchemy reads it but never writes it.


class HierarchyEdge(Base):
    """One asserted named parent edge, mirrored from Oxigraph for the tree.

    `kind` is 'class' (rdfs:subClassOf) or 'property' (rdfs:subPropertyOf), so
    one table serves both hierarchies.

    The four columns are marked as a composite key only because SQLAlchemy
    requires a primary key to map a table; the migration deliberately creates
    none. A graph is a set of triples so an edge cannot repeat anyway (verified
    on DRON — 777,706 edges, 0 duplicates), and the key's index measured 186 MB
    against 84 MB for the narrow (version_id, kind, child) index that serves the
    same lookups.
    """
    __tablename__ = "hierarchy_edge"

    version_id: Mapped[str] = mapped_column(
        ForeignKey("versions.id", ondelete="CASCADE"), primary_key=True)
    child: Mapped[str] = mapped_column(Text, primary_key=True)
    parent: Mapped[str] = mapped_column(Text, primary_key=True)
    kind: Mapped[str] = mapped_column(String, primary_key=True)


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


class OntologyMaintainer(Base):
    """A user granted maintainer rights over a specific existing ontology.
    Created when an 'ontology' maintainer request is approved."""
    __tablename__ = "ontology_maintainers"
    __table_args__ = (UniqueConstraint("user_id", "ontology_id"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    ontology_id: Mapped[str] = mapped_column(ForeignKey("ontologies.id", ondelete="CASCADE"))
    granted_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MaintainerRequest(Base):
    """A user's request for maintainer rights: either over an existing ontology
    (request_type='ontology', ontology_id set) or the global ability to add new
    ontologies (request_type='uploader'). Admins approve/deny with a note."""
    __tablename__ = "maintainer_requests"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    request_type: Mapped[str] = mapped_column(String, nullable=False)  # "ontology" | "uploader"
    ontology_id: Mapped[str | None] = mapped_column(
        ForeignKey("ontologies.id", ondelete="CASCADE"), nullable=True
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)          # user rationale
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending", server_default="pending")
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)  # admin rationale (optional)
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UsageDaily(Base):
    """Per-ontology daily view/download aggregates.

    Written by the Celery rollup task from Redis counters (absolute counts, so
    the upsert is idempotent). Daily grain so week/month/year trends are all
    derivable on read via date_trunc; no raw event log and no per-visitor rows
    are ever stored (dedup happens ephemerally in Redis). `unique_count` = one
    per visitor per UTC day (deduped); `total_count` = every counted hit.
    """
    __tablename__ = "usage_daily"
    __table_args__ = (
        UniqueConstraint("ontology_id", "kind", "day", name="uq_usage_daily"),
        Index("ix_usage_daily_day", "day"),
        Index("ix_usage_daily_onto_day", "ontology_id", "day"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    ontology_id: Mapped[str] = mapped_column(ForeignKey("ontologies.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String, nullable=False)  # "view" | "download"
    day: Mapped[date] = mapped_column(Date, nullable=False)    # UTC calendar day
    unique_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ReasonerProfile(Base):
    """An admin-defined, named reasoner configuration: a reasoner backend plus the
    parameters passed to it at reasoning time. Selectable when adding an ontology
    (dashboard/admin) and in the re-index control.

    `dashboard_selectable` gates visibility in the user dashboard (admins always
    see all). Exactly one profile should have `is_default` = true (used when none
    is chosen). Deletion is soft (`archived` = true): the row is kept for
    provenance and existing references still resolve, but it is dropped from all
    selection lists. Name uniqueness among non-archived profiles is enforced in
    the API layer.
    """
    __tablename__ = "reasoner_profiles"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, nullable=False)
    reasoner: Mapped[str] = mapped_column(String, nullable=False)  # backend name (rustdl/konclude/km/rdflib)
    params: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    dashboard_selectable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
