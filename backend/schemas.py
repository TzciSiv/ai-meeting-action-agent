from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


ActionStatus = Literal["Open", "In Progress", "Done"]


class ActionItemBase(BaseModel):
    task: str = Field(..., min_length=1)
    owner: str = "Unassigned"
    deadline: str = "Not mentioned"
    evidence: str = ""


class ActionCreate(ActionItemBase):
    status: ActionStatus = "Open"


class ActionUpdate(BaseModel):
    task: str | None = None
    owner: str | None = None
    deadline: str | None = None
    evidence: str | None = None
    status: ActionStatus | None = None


class ActionRead(ActionItemBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    meeting_id: int
    status: ActionStatus
    source_run_id: str
    created_at: datetime
    updated_at: datetime


class UserCreate(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=6, max_length=128)


class UserLogin(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=1, max_length=128)


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    role: str
    created_at: datetime


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserRead


class MeetingUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=200)


class FollowUpSource(BaseModel):
    chunk_index: int
    content: str
    rank: int
    score: float


class MeetingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    transcript: str
    summary_markdown: str
    summary: dict[str, Any]
    decisions: list[str]
    risks: list[str]
    follow_up_question: str
    follow_up_answer: str
    follow_up_sources: list[FollowUpSource]
    run_id: str | None = None
    ai_run_ids: list[str] = Field(default_factory=list)
    prompt_version: str = ""
    model: str = ""
    generation_latency_ms: int = 0
    embedding_model: str = ""
    chunking_version: str = ""
    embedding_status: str = "not_started"
    last_embedded_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    actions: list[ActionRead]


class MeetingListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    follow_up_question: str
    follow_up_answer: str
    created_at: datetime
    updated_at: datetime
    action_count: int
    done_count: int


class AuditEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    action: str
    resource_type: str
    resource_id: str
    event_type: str
    entity_type: str
    entity_id: str
    status: str
    request_id: str
    run_id: str = ""
    metadata: dict[str, Any]
    ip_hash: str
    user_agent_hash: str
    created_at: datetime


class AuditEventPageRead(BaseModel):
    items: list[AuditEventRead]
    page: int
    page_size: int
    total: int
    total_pages: int


class PromptVersionRead(BaseModel):
    id: int
    prompt_id: str
    version: str
    task_type: str
    model: str
    temperature: float
    template_hash: str
    created_by: int | None
    created_at: datetime


class AiRunRead(BaseModel):
    id: int
    run_id: str
    user_id: int | None
    meeting_id: int | None
    prompt_version_id: int | None
    prompt_version: PromptVersionRead | None = None
    model: str
    retrieved_chunk_ids: list[str]
    output_hash: str
    latency_ms: int
    input_tokens: int
    output_tokens: int
    cost_estimate: float
    created_at: datetime


class IngestionJobRead(BaseModel):
    id: int
    job_id: str
    user_id: int | None
    meeting_id: int | None
    source_type: str
    filename: str
    file_size_bytes: int
    status: str
    current_step: str
    error_message: str
    created_at: datetime
    updated_at: datetime


class IngestResponse(BaseModel):
    job_id: str
    status: str
    meeting_id: int | None = None
    current_step: str
    file_size_bytes: int = 0


class PipelineTopicMetric(BaseModel):
    topic: str
    pending: int = 0
    published: int = 0
    failed: int = 0
    processed: int = 0


class WorkerStatusRead(BaseModel):
    id: int
    worker_id: str
    display_name: str
    hostname: str
    mode: str
    status: str
    current_topic: str
    current_job_id: str
    current_event_type: str
    processed_count: int
    failed_count: int
    last_error: str
    started_at: datetime
    last_seen_at: datetime
    seconds_since_seen: int


class PipelineOperationsRead(BaseModel):
    expected_worker_count: int = 0
    reporting_worker_count: int = 0
    missing_worker_count: int = 0
    stale_worker_count: int = 0
    job_counts: dict[str, int]
    workers: list[WorkerStatusRead] = Field(default_factory=list)
    kafka_topics: list[PipelineTopicMetric]
    failed_job_count: int = 0
    failed_jobs: list[IngestionJobRead]
