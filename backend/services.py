import json
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from .analysis_graph import CHUNK_OVERLAP, CHUNK_SIZE, embedding_model_name, run_meeting_analysis_graph
from .exports import build_agent_report_docx
from .governance import (
    active_prompt_versions,
    ai_budget_available,
    can_access_meeting,
    get_ai_run,
    is_not_mentioned_answer,
    persist_ai_run_traces,
    prompt_version_label,
)
from .models import ActionItem, AiRun, AuditEvent, IngestionJob, Meeting, PromptVersion, User
from .observability import get_request_id, sanitize_fields
from .schemas import ActionCreate, ActionUpdate, MeetingUpdate


VALID_STATUSES = {"Open", "In Progress", "Done"}


def make_title(transcript: str, provided_title: str | None = None) -> str:
    if provided_title and provided_title.strip():
        return provided_title.strip()[:200]
    words = transcript.strip().replace("\n", " ").split()
    title = " ".join(words[:8]).strip(" ,.;:")
    return title[:200] or "Untitled meeting"


def build_analysis(
    transcript: str,
    follow_up_question: str = "",
    meeting_id: int = 0,
    user_id: int | None = None,
    prompt_version_ids: dict[str, int] | None = None,
) -> dict[str, Any]:
    return run_meeting_analysis_graph(
        transcript=transcript,
        follow_up_question=follow_up_question,
        meeting_id=meeting_id,
        user_id=user_id,
        prompt_version_ids=prompt_version_ids,
    )


def serialize_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def parse_json(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def action_to_dict(action: ActionItem) -> dict[str, Any]:
    return {
        "id": action.id,
        "meeting_id": action.meeting_id,
        "task": action.task,
        "owner": action.owner,
        "deadline": action.deadline,
        "evidence": action.evidence,
        "status": action.status,
        "source_run_id": action.source_run_id,
        "created_at": action.created_at,
        "updated_at": action.updated_at,
    }


def meeting_to_dict(meeting: Meeting) -> dict[str, Any]:
    ai_run_ids = parse_json(meeting.ai_run_ids_json, [])
    return {
        "id": meeting.id,
        "title": meeting.title,
        "transcript": meeting.transcript,
        "summary_markdown": meeting.summary_markdown,
        "summary": parse_json(meeting.summary_json, {}),
        "decisions": parse_json(meeting.decisions_json, []),
        "risks": parse_json(meeting.risks_json, []),
        "follow_up_question": meeting.follow_up_question,
        "follow_up_answer": meeting.follow_up_answer,
        "follow_up_sources": parse_json(meeting.follow_up_sources_json, []),
        "run_id": ai_run_ids[0] if ai_run_ids else None,
        "ai_run_ids": ai_run_ids,
        "prompt_version": meeting.prompt_version,
        "model": meeting.model,
        "generation_latency_ms": meeting.generation_latency_ms,
        "embedding_model": meeting.embedding_model,
        "chunking_version": meeting.chunking_version,
        "embedding_status": meeting.embedding_status,
        "last_embedded_at": meeting.last_embedded_at,
        "created_at": meeting.created_at,
        "updated_at": meeting.updated_at,
        "actions": [action_to_dict(action) for action in meeting.actions],
    }


def meeting_list_item(meeting: Meeting) -> dict[str, Any]:
    action_count = len(meeting.actions)
    done_count = sum(1 for action in meeting.actions if action.status == "Done")
    return {
        "id": meeting.id,
        "title": meeting.title,
        "follow_up_question": meeting.follow_up_question,
        "follow_up_answer": meeting.follow_up_answer,
        "created_at": meeting.created_at,
        "updated_at": meeting.updated_at,
        "action_count": action_count,
        "done_count": done_count,
    }


def primary_run_id_for_audit_event(db: Session | None, event: AuditEvent, metadata: dict[str, Any]) -> str:
    direct_run_id = metadata.get("run_id") or metadata.get("primary_run_id")
    if isinstance(direct_run_id, str):
        return direct_run_id
    if db is None or event.action != "meeting.ingest" or event.resource_type != "ingestion_job" or not event.resource_id:
        return ""

    job = db.scalar(select(IngestionJob).where(IngestionJob.job_id == event.resource_id))
    if job is None or job.meeting_id is None:
        return ""
    meeting = db.get(Meeting, job.meeting_id)
    if meeting is None:
        return ""
    ai_run_ids = parse_json(meeting.ai_run_ids_json, [])
    return ai_run_ids[0] if ai_run_ids and isinstance(ai_run_ids[0], str) else ""


def audit_event_to_dict(event: AuditEvent, db: Session | None = None) -> dict[str, Any]:
    metadata = parse_json(event.metadata_json, {})
    return {
        "id": event.id,
        "action": event.action,
        "resource_type": event.resource_type,
        "resource_id": event.resource_id,
        "event_type": event.action,
        "entity_type": event.resource_type,
        "entity_id": event.resource_id,
        "status": event.status,
        "request_id": event.request_id,
        "run_id": primary_run_id_for_audit_event(db, event, metadata),
        "metadata": metadata,
        "ip_hash": event.ip_hash,
        "user_agent_hash": event.user_agent_hash,
        "created_at": event.created_at,
    }


def prompt_version_to_dict(prompt_version: PromptVersion) -> dict[str, Any]:
    return {
        "id": prompt_version.id,
        "prompt_id": prompt_version.prompt_id,
        "version": prompt_version.version,
        "task_type": prompt_version.task_type,
        "model": prompt_version.model,
        "temperature": prompt_version.temperature,
        "template_hash": prompt_version.template_hash,
        "created_by": prompt_version.created_by,
        "created_at": prompt_version.created_at,
    }


def ai_run_to_dict(run: AiRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "run_id": run.run_id,
        "user_id": run.user_id,
        "meeting_id": run.meeting_id,
        "prompt_version_id": run.prompt_version_id,
        "prompt_version": prompt_version_to_dict(run.prompt_version) if run.prompt_version is not None else None,
        "model": run.model,
        "retrieved_chunk_ids": parse_json(run.retrieved_chunk_ids_json, []),
        "output_hash": run.output_hash,
        "latency_ms": run.latency_ms,
        "input_tokens": run.input_tokens,
        "output_tokens": run.output_tokens,
        "cost_estimate": run.cost_estimate,
        "created_at": run.created_at,
    }


def record_audit_event(
    db: Session,
    event_type: str,
    user_id: int | None = None,
    entity_type: str = "",
    entity_id: int | str | None = None,
    status: str = "success",
    metadata: dict[str, Any] | None = None,
    ip_hash: str = "",
    user_agent_hash: str = "",
) -> AuditEvent:
    event = AuditEvent(
        actor_user_id=user_id,
        action=event_type,
        resource_type=entity_type,
        resource_id="" if entity_id is None else str(entity_id),
        status=status,
        request_id=get_request_id(),
        metadata_json=serialize_json(sanitize_fields(metadata or {})),
        ip_hash=ip_hash,
        user_agent_hash=user_agent_hash,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def audit_event_scope(user: User):
    statement = select(AuditEvent)
    if user.role != "admin":
        statement = statement.where(AuditEvent.actor_user_id == user.id)
    return statement


def count_audit_events(db: Session, user: User) -> int:
    scoped = audit_event_scope(user).subquery()
    return int(db.scalar(select(func.count()).select_from(scoped)) or 0)


def list_audit_events(db: Session, user: User, page: int = 1, page_size: int = 20) -> list[AuditEvent]:
    bounded_page = max(page, 1)
    bounded_page_size = min(max(page_size, 1), 100)
    statement = (
        audit_event_scope(user)
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        .offset((bounded_page - 1) * bounded_page_size)
        .limit(bounded_page_size)
    )
    return list(db.scalars(statement))


def analyze_meeting_record(
    db: Session,
    meeting: Meeting,
    follow_up_question: str = "",
    user_id: int | None = None,
) -> Meeting:
    if not ai_budget_available(db, user_id):
        raise ValueError("Per-user AI spend limit reached")

    prompt_versions = active_prompt_versions(db)
    prompt_version_ids = {prompt_id: prompt_version.id for prompt_id, prompt_version in prompt_versions.items()}
    meeting.follow_up_question = follow_up_question.strip()
    meeting.embedding_status = "processing"
    meeting.embedding_model = embedding_model_name()
    meeting.chunking_version = f"recursive-{CHUNK_SIZE}-{CHUNK_OVERLAP}"
    db.flush()
    try:
        analysis = build_analysis(
            transcript=meeting.transcript,
            follow_up_question=meeting.follow_up_question,
            meeting_id=meeting.id,
            user_id=user_id,
            prompt_version_ids=prompt_version_ids,
        )
    except Exception:
        meeting.embedding_status = "failed"
        db.rollback()
        raise

    meeting.transcript = analysis.get("transcript", meeting.transcript)
    meeting.summary_markdown = analysis.get("summary_markdown", "")
    meeting.summary_json = serialize_json(analysis.get("summary", {}))
    meeting.decisions_json = serialize_json(analysis.get("decisions", []))
    meeting.risks_json = serialize_json(analysis.get("risks", []))
    meeting.follow_up_answer = str(analysis.get("follow_up_answer", "")).strip()
    follow_up_sources = [] if is_not_mentioned_answer(meeting.follow_up_answer) else analysis.get("follow_up_sources", [])
    analysis["follow_up_sources"] = follow_up_sources
    meeting.follow_up_sources_json = serialize_json(follow_up_sources)

    traces = list(analysis.get("ai_run_traces", []))
    ai_runs = persist_ai_run_traces(db, traces, user_id=user_id, meeting_id=meeting.id)
    ai_run_ids = [run.run_id for run in ai_runs]
    primary_run_id = ai_run_ids[0] if ai_run_ids else ""
    meeting.ai_run_ids_json = serialize_json(ai_run_ids)
    meeting.generation_latency_ms = sum(int(trace.get("latency_ms", 0)) for trace in traces)
    meeting.model = ", ".join(sorted({prompt_version.model for prompt_version in prompt_versions.values()}))
    meeting.prompt_version = ", ".join(
        sorted(prompt_version_label(prompt_version) for prompt_version in prompt_versions.values())
    )
    meeting.embedding_status = "completed"
    from .models import utc_now

    meeting.last_embedded_at = utc_now()

    for item in analysis.get("action_items", []):
        db.add(
            ActionItem(
                meeting_id=meeting.id,
                task=str(item.get("task", "Unspecified task")),
                owner=str(item.get("owner", "Unassigned") or "Unassigned"),
                deadline=str(item.get("deadline", "Not mentioned") or "Not mentioned"),
                evidence=str(item.get("evidence", "") or ""),
                status="Open",
                source_run_id=primary_run_id,
            )
        )

    db.commit()
    db.refresh(meeting)
    return get_meeting(db, meeting.id)


def list_meetings_for_user(db: Session, user: User) -> list[Meeting]:
    statement = (
        select(Meeting)
        .options(selectinload(Meeting.actions), selectinload(Meeting.permissions))
        .order_by(Meeting.created_at.desc(), Meeting.id.desc())
    )
    meetings = list(db.scalars(statement))
    return [meeting for meeting in meetings if can_access_meeting(db, meeting, user)]


def get_meeting(db: Session, meeting_id: int, user_id: int | None = None) -> Meeting:
    statement = select(Meeting).options(selectinload(Meeting.actions)).where(Meeting.id == meeting_id)
    if user_id is not None:
        statement = statement.where(Meeting.user_id == user_id)
    meeting = db.scalar(statement)
    if meeting is None:
        raise LookupError("Meeting not found")
    return meeting


def get_meeting_for_user(
    db: Session,
    meeting_id: int,
    user: User,
    require_raw_transcript: bool = False,
) -> Meeting:
    statement = select(Meeting).options(selectinload(Meeting.actions), selectinload(Meeting.permissions)).where(Meeting.id == meeting_id)
    meeting = db.scalar(statement)
    if meeting is None or not can_access_meeting(db, meeting, user, require_raw_transcript=require_raw_transcript):
        raise LookupError("Meeting not found")
    return meeting


def get_action(db: Session, action_id: int, user_id: int | None = None) -> ActionItem:
    statement = select(ActionItem).where(ActionItem.id == action_id)
    if user_id is not None:
        statement = statement.join(Meeting).where(Meeting.user_id == user_id)
    item = db.scalar(statement)
    if item is None:
        raise LookupError("Action not found")
    return item


def update_meeting(db: Session, meeting_id: int, update: MeetingUpdate, user_id: int | None = None) -> Meeting:
    meeting = get_meeting(db, meeting_id, user_id=user_id)
    updates = update.model_dump(exclude_unset=True)

    if "title" in updates and updates["title"] is not None:
        title = updates["title"].strip()
        if not title:
            raise ValueError("Meeting name is required")
        meeting.title = title[:200]

    db.commit()
    db.refresh(meeting)
    return get_meeting(db, meeting.id, user_id=user_id)


def add_action(db: Session, meeting_id: int, action: ActionCreate, user_id: int | None = None) -> ActionItem:
    get_meeting(db, meeting_id, user_id=user_id)
    item = ActionItem(
        meeting_id=meeting_id,
        task=action.task,
        owner=action.owner or "Unassigned",
        deadline=action.deadline or "Not mentioned",
        evidence=action.evidence or "",
        status=action.status,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def update_action(db: Session, action_id: int, update: ActionUpdate, user_id: int | None = None) -> ActionItem:
    item = get_action(db, action_id, user_id=user_id)
    updates = update.model_dump(exclude_unset=True)
    if "status" in updates and updates["status"] not in VALID_STATUSES:
        raise ValueError("Invalid action status")
    for key, value in updates.items():
        if value is not None:
            setattr(item, key, value)

    db.commit()
    db.refresh(item)
    return item


def delete_action(db: Session, action_id: int, user_id: int | None = None) -> None:
    item = get_action(db, action_id, user_id=user_id)
    db.delete(item)
    db.commit()


def delete_meeting(db: Session, meeting_id: int, user_id: int | None = None) -> None:
    meeting = get_meeting(db, meeting_id, user_id=user_id)
    db.delete(meeting)
    db.commit()


def export_meeting_report(db: Session, meeting_id: int, user_id: int | None = None) -> bytes:
    meeting = get_meeting(db, meeting_id, user_id=user_id)
    return build_agent_report_docx(
        transcript=meeting.transcript,
        summary_markdown=meeting.summary_markdown,
        actions=[action_to_dict(action) for action in meeting.actions],
        decisions=parse_json(meeting.decisions_json, []),
        risks=parse_json(meeting.risks_json, []),
        follow_up_question=meeting.follow_up_question,
        follow_up_answer=meeting.follow_up_answer,
    )


def get_ai_run_for_user(db: Session, run_id: str, user: User) -> AiRun:
    run = get_ai_run(db, run_id)
    if user.role == "admin":
        return run
    if run.meeting is not None and not can_access_meeting(db, run.meeting, user):
        raise PermissionError("AI run not found")
    if run.meeting is None and run.user_id != user.id:
        raise PermissionError("AI run not found")
    return run


def list_prompt_version_dicts(db: Session) -> list[dict[str, Any]]:
    active_versions = active_prompt_versions(db)
    return [
        prompt_version_to_dict(prompt_version)
        for prompt_version in sorted(
            active_versions.values(),
            key=lambda prompt_version: (prompt_version.task_type, prompt_version.prompt_id),
        )
    ]
