import hashlib
import json
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from .models import AiRun, Meeting, MeetingPermission, PromptVersion, User
from .prompts import PromptSpec, get_prompt_specs


NOT_MENTIONED_RESPONSE = "Not mentioned"


def is_not_mentioned_answer(answer: str) -> bool:
    normalized = str(answer or "").strip()
    return normalized.rstrip(".").casefold() == NOT_MENTIONED_RESPONSE.casefold()


def hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def safe_hash(value: str | None) -> str:
    value = (value or "").strip()
    return hash_text(value) if value else ""


def output_hash(value: Any) -> str:
    return hash_text(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str))


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4) if text else 0


def estimate_cost(input_tokens: int, output_tokens: int) -> float:
    # Local estimate only. Production deployments should replace this with provider-specific billing telemetry.
    input_rate = float(os.getenv("OPENAI_INPUT_TOKEN_COST_PER_1K", "0"))
    output_rate = float(os.getenv("OPENAI_OUTPUT_TOKEN_COST_PER_1K", "0"))
    return round((input_tokens / 1000 * input_rate) + (output_tokens / 1000 * output_rate), 6)


def prompt_version_label(prompt_version: PromptVersion | None) -> str:
    if prompt_version is None:
        return ""
    return f"{prompt_version.prompt_id}@{prompt_version.version}"


def sync_prompt_registry(db: Session, created_by: int | None = None) -> list[PromptVersion]:
    """Ensure code-registered prompts also exist in the DB registry."""
    synced: list[PromptVersion] = []
    created: list[PromptVersion] = []
    for spec in get_prompt_specs().values():
        statement = select(PromptVersion).where(
            PromptVersion.prompt_id == spec.prompt_id,
            PromptVersion.version == spec.version,
            PromptVersion.template_hash == spec.template_hash,
        )
        prompt_version = db.scalar(statement)
        if prompt_version is None:
            prompt_version = PromptVersion(
                prompt_id=spec.prompt_id,
                version=spec.version,
                task_type=spec.task_type,
                model=spec.model_name(),
                temperature=spec.temperature,
                template_hash=spec.template_hash,
                created_by=created_by,
            )
            db.add(prompt_version)
            created.append(prompt_version)
        else:
            prompt_version.model = spec.model_name()
            prompt_version.temperature = spec.temperature
            prompt_version.task_type = spec.task_type
        synced.append(prompt_version)
    db.commit()
    for prompt_version in synced:
        db.refresh(prompt_version)
    return synced


def active_prompt_versions(db: Session) -> dict[str, PromptVersion]:
    synced = sync_prompt_registry(db)
    active: dict[str, PromptVersion] = {}
    for spec in get_prompt_specs().values():
        matching = next(
            (
                prompt_version
                for prompt_version in synced
                if prompt_version.prompt_id == spec.prompt_id
                and prompt_version.version == spec.version
                and prompt_version.template_hash == spec.template_hash
            ),
            None,
        )
        if matching is None:
            raise RuntimeError(f"Prompt {spec.prompt_id}@{spec.version} is missing from the prompt registry")
        active[spec.prompt_id] = matching
    return active


def meeting_permission(db: Session, meeting_id: int, user_id: int) -> MeetingPermission | None:
    return db.scalar(
        select(MeetingPermission).where(
            MeetingPermission.meeting_id == meeting_id,
            MeetingPermission.user_id == user_id,
        )
    )


def can_access_meeting(
    db: Session,
    meeting: Meeting,
    user: User,
    require_raw_transcript: bool = False,
) -> bool:
    if meeting.user_id == user.id:
        return True
    permission = meeting_permission(db, meeting.id, user.id)
    if permission is None:
        return False
    if require_raw_transcript and not permission.can_view_transcript:
        return False
    if user.role == "reviewer":
        return permission.access_level in {"reviewer", "owner"}
    if user.role == "admin":
        return permission.access_level in {"admin", "reviewer", "owner"}
    return permission.access_level in {"reviewer", "owner"}


def make_ai_run_trace(
    prompt: PromptSpec,
    prompt_version_id: int | None,
    model: str,
    messages: list[tuple[str, str]],
    output: Any,
    start_time: float,
    retrieved_chunk_ids: list[str] | None = None,
) -> dict[str, Any]:
    output_payload = output.model_dump() if hasattr(output, "model_dump") else output
    input_text = "\n".join(content for _, content in messages)
    output_text = json.dumps(output_payload, ensure_ascii=False, default=str)
    input_tokens = estimate_tokens(input_text)
    output_tokens = estimate_tokens(output_text)
    return {
        "run_id": uuid.uuid4().hex,
        "prompt_id": prompt.prompt_id,
        "prompt_version": prompt.version,
        "prompt_version_id": prompt_version_id,
        "model": model,
        "retrieved_chunk_ids": retrieved_chunk_ids or [],
        "output_hash": output_hash(output_payload),
        "latency_ms": int((time.perf_counter() - start_time) * 1000),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_estimate": estimate_cost(input_tokens, output_tokens),
    }


def persist_ai_run_traces(
    db: Session,
    traces: list[dict[str, Any]],
    user_id: int | None,
    meeting_id: int | None,
) -> list[AiRun]:
    runs: list[AiRun] = []
    for trace in traces:
        run = AiRun(
            run_id=str(trace.get("run_id") or uuid.uuid4().hex),
            user_id=user_id,
            meeting_id=meeting_id,
            prompt_version_id=trace.get("prompt_version_id"),
            model=str(trace.get("model", "")),
            retrieved_chunk_ids_json=json.dumps(trace.get("retrieved_chunk_ids", []), ensure_ascii=False),
            output_hash=str(trace.get("output_hash", "")),
            latency_ms=int(trace.get("latency_ms", 0)),
            input_tokens=int(trace.get("input_tokens", 0)),
            output_tokens=int(trace.get("output_tokens", 0)),
            cost_estimate=float(trace.get("cost_estimate", 0.0)),
        )
        db.add(run)
        runs.append(run)
    return runs


def get_ai_run(db: Session, run_id: str) -> AiRun:
    run = db.scalar(
        select(AiRun)
        .options(selectinload(AiRun.prompt_version), selectinload(AiRun.meeting))
        .where(AiRun.run_id == run_id)
    )
    if run is None:
        raise LookupError("AI run not found")
    return run


def ai_budget_available(db: Session, user_id: int | None) -> bool:
    if user_id is None:
        return True
    daily_limit = float(os.getenv("USER_DAILY_AI_COST_LIMIT", "0"))
    if daily_limit <= 0:
        return True
    since = datetime.now(timezone.utc) - timedelta(days=1)
    spent = (
        db.scalar(
            select(func.coalesce(func.sum(AiRun.cost_estimate), 0.0)).where(
                AiRun.user_id == user_id,
                AiRun.created_at >= since,
            )
        )
        or 0.0
    )
    return float(spent) < daily_limit
