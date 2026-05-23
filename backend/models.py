from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Meeting(Base):
    __tablename__ = "meetings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    transcript: Mapped[str] = mapped_column(Text, nullable=False)
    summary_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    summary_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    decisions_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    risks_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    follow_up_question: Mapped[str] = mapped_column(Text, nullable=False, default="")
    follow_up_answer: Mapped[str] = mapped_column(Text, nullable=False, default="")
    follow_up_sources_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    ai_run_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    prompt_version: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    model: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    generation_latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    embedding_model: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    chunking_version: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    embedding_status: Mapped[str] = mapped_column(String(40), nullable=False, default="not_started")
    last_embedded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    user: Mapped["User | None"] = relationship(back_populates="meetings")
    actions: Mapped[list["ActionItem"]] = relationship(
        back_populates="meeting",
        cascade="all, delete-orphan",
        order_by="ActionItem.id",
    )
    ai_runs: Mapped[list["AiRun"]] = relationship(back_populates="meeting", cascade="all, delete-orphan")
    permissions: Mapped[list["MeetingPermission"]] = relationship(back_populates="meeting", cascade="all, delete-orphan")
    ingestion_jobs: Mapped[list["IngestionJob"]] = relationship(back_populates="meeting")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(40), nullable=False, default="owner", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    meetings: Mapped[list[Meeting]] = relationship(back_populates="user")
    audit_events: Mapped[list["AuditEvent"]] = relationship(back_populates="user")
    meeting_permissions: Mapped[list["MeetingPermission"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class ActionItem(Base):
    __tablename__ = "action_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False, index=True)
    task: Mapped[str] = mapped_column(Text, nullable=False)
    owner: Mapped[str] = mapped_column(String(120), nullable=False, default="Unassigned")
    deadline: Mapped[str] = mapped_column(String(120), nullable=False, default="Not mentioned")
    evidence: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="Open")
    source_run_id: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    meeting: Mapped[Meeting] = relationship(back_populates="actions")


class MeetingPermission(Base):
    __tablename__ = "meeting_permissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    access_level: Mapped[str] = mapped_column(String(40), nullable=False, default="reviewer")
    can_view_transcript: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    meeting: Mapped[Meeting] = relationship(back_populates="permissions")
    user: Mapped[User] = relationship(back_populates="meeting_permissions")


class PromptVersion(Base):
    __tablename__ = "prompt_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    prompt_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    task_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    temperature: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    template_hash: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    ai_runs: Mapped[list["AiRun"]] = relationship(back_populates="prompt_version")


class AiRun(Base):
    __tablename__ = "ai_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    run_id: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    meeting_id: Mapped[int | None] = mapped_column(ForeignKey("meetings.id", ondelete="CASCADE"), nullable=True, index=True)
    prompt_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("prompt_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    model: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    retrieved_chunk_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    output_hash: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_estimate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    meeting: Mapped[Meeting | None] = relationship(back_populates="ai_runs")
    prompt_version: Mapped[PromptVersion | None] = relationship(back_populates="ai_runs")


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    job_id: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    meeting_id: Mapped[int | None] = mapped_column(ForeignKey("meetings.id", ondelete="SET NULL"), nullable=True, index=True)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_uri: Mapped[str] = mapped_column(Text, nullable=False, default="")
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    follow_up_question: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="queued", index=True)
    current_step: Mapped[str] = mapped_column(String(80), nullable=False, default="queued")
    error_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    meeting: Mapped[Meeting | None] = relationship(back_populates="ingestion_jobs")


class EventOutbox(Base):
    __tablename__ = "event_outbox"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    event_id: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    topic: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(120), nullable=False, default="", index=True)
    event_type: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    event_version: Mapped[str] = mapped_column(String(20), nullable=False, default="1")
    envelope_json: Mapped[str] = mapped_column(Text, nullable=False)
    publish_status: Mapped[str] = mapped_column(String(40), nullable=False, default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    worker_id: Mapped[str] = mapped_column(String(160), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    hostname: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    mode: Mapped[str] = mapped_column(String(40), nullable=False, default="kafka")
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="starting", index=True)
    current_topic: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    current_job_id: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    current_event_type: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    processed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    action: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    resource_id: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="success")
    request_id: Mapped[str] = mapped_column(String(80), nullable=False, default="", index=True)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    ip_hash: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    user_agent_hash: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    user: Mapped[User | None] = relationship(back_populates="audit_events")
