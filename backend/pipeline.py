import json
import os
import re
import uuid
from pathlib import Path
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import PROJECT_ROOT
from .events import (
    TOPIC_ANALYSIS_COMPLETED,
    TOPIC_ANALYSIS_FAILED,
    TOPIC_ANALYSIS_REQUESTED,
    TOPIC_EMBEDDINGS_CREATED,
    TOPIC_MEETING_UPLOADED,
    TOPIC_TRANSCRIPT_TRANSCRIBED,
    TOPIC_TRANSCRIPTION_FAILED,
    TOPIC_TRANSCRIPTION_REQUESTED,
    enqueue_event,
)
from .llm import transcribe_audio
from .models import EventOutbox, IngestionJob, Meeting, WorkerHeartbeat, utc_now
from .observability import increment_counter
from .services import analyze_meeting_record, make_title
from .transcript_import import extract_docx_transcript


UPLOAD_DIR = PROJECT_ROOT / "data" / "ingestion_uploads"
TRANSCRIPTION_RESULT_DIR = PROJECT_ROOT / "data" / "transcription_results"
TRANSCRIPTION_JOB_SOURCE_TYPE = "transcription_audio"


def int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


WORKER_STALE_AFTER_SECONDS = max(int_env("WORKER_HEARTBEAT_STALE_AFTER_SECONDS", 90), 1)
EXPECTED_WORKER_COUNT = max(int_env("BACKEND_WORKER_REPLICAS", 3), 0)
QUEUE_RECOVERY_AFTER_SECONDS = max(int_env("WORKER_QUEUE_RECOVERY_SECONDS", 5), 1)
WORKER_HEARTBEAT_RETAIN_COUNT = max(int_env("WORKER_HEARTBEAT_RETAIN_COUNT", 10), 1)


def datetime_after(value: datetime, cutoff: datetime) -> bool:
    if value.tzinfo is None and cutoff.tzinfo is not None:
        value = value.replace(tzinfo=cutoff.tzinfo)
    elif value.tzinfo is not None and cutoff.tzinfo is None:
        cutoff = cutoff.replace(tzinfo=value.tzinfo)
    return value > cutoff


def seconds_between(later: datetime, earlier: datetime) -> int:
    if later.tzinfo is None and earlier.tzinfo is not None:
        later = later.replace(tzinfo=earlier.tzinfo)
    elif later.tzinfo is not None and earlier.tzinfo is None:
        earlier = earlier.replace(tzinfo=later.tzinfo)
    return max(0, int((later - earlier).total_seconds()))


def worker_heartbeat_group(worker_id: str) -> str:
    return worker_id.split(":", 1)[0] if ":" in worker_id else worker_id


def prune_worker_heartbeats(db: Session, worker_id: str, retain_count: int = WORKER_HEARTBEAT_RETAIN_COUNT) -> None:
    worker_group = worker_heartbeat_group(worker_id)
    workers = list(
        db.scalars(
            select(WorkerHeartbeat).order_by(
                WorkerHeartbeat.last_seen_at.desc(),
                WorkerHeartbeat.id.desc(),
            )
        )
    )
    matching_workers = [
        worker
        for worker in workers
        if worker_heartbeat_group(worker.worker_id) == worker_group
    ]
    for retired_worker in matching_workers[retain_count:]:
        db.delete(retired_worker)


def new_job_id() -> str:
    return uuid.uuid4().hex


def safe_filename(filename: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", filename.strip())
    return cleaned[:180] or "upload.bin"


def save_upload_bytes(job_id: str, filename: str, content: bytes) -> str:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = safe_filename(filename)
    target = (UPLOAD_DIR / f"{job_id}_{safe_name}").resolve()
    root = UPLOAD_DIR.resolve()
    if not str(target).startswith(str(root)):
        raise ValueError("Invalid upload path")
    target.write_bytes(content)
    return str(target)


def transcription_result_path(job_id: str) -> Path:
    if not re.fullmatch(r"[A-Fa-f0-9]{32}", job_id):
        raise ValueError("Invalid transcription job ID")
    return (TRANSCRIPTION_RESULT_DIR / f"{job_id}.txt").resolve()


def write_transcription_result(job_id: str, transcript: str) -> None:
    TRANSCRIPTION_RESULT_DIR.mkdir(parents=True, exist_ok=True)
    transcription_result_path(job_id).write_text(transcript, encoding="utf-8")


def read_transcription_result(job: IngestionJob) -> str:
    if job.source_type != TRANSCRIPTION_JOB_SOURCE_TYPE:
        raise LookupError("Transcript is not available for this job")
    if job.status != "completed":
        raise LookupError("Transcription is not complete")
    path = transcription_result_path(job.job_id)
    if not path.exists():
        raise LookupError("Transcript result not found")
    return path.read_text(encoding="utf-8")


def create_meeting_stub(db: Session, user_id: int | None, transcript: str, title: str | None, follow_up_question: str) -> Meeting:
    meeting = Meeting(
        user_id=user_id,
        title=make_title(transcript, title),
        transcript=transcript,
        summary_markdown="",
        summary_json="{}",
        decisions_json="[]",
        risks_json="[]",
        follow_up_question=follow_up_question.strip(),
        follow_up_answer="",
        follow_up_sources_json="[]",
        embedding_status="not_started",
    )
    db.add(meeting)
    db.flush()
    return meeting


def job_to_dict(job: IngestionJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "job_id": job.job_id,
        "user_id": job.user_id,
        "meeting_id": job.meeting_id,
        "source_type": job.source_type,
        "filename": job.filename,
        "file_size_bytes": job.file_size_bytes,
        "status": job.status,
        "current_step": job.current_step,
        "error_message": job.error_message,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


def create_ingestion_job(
    db: Session,
    user_id: int,
    source_type: str,
    job_id: str | None = None,
    title: str | None = None,
    follow_up_question: str = "",
    filename: str = "",
    file_size_bytes: int = 0,
    source_uri: str = "",
    transcript: str | None = None,
) -> IngestionJob:
    job_id = job_id or new_job_id()
    meeting = None
    if source_type == "transcript":
        meeting = create_meeting_stub(db, user_id, transcript or "", title, follow_up_question)

    job = IngestionJob(
        job_id=job_id,
        user_id=user_id,
        meeting_id=meeting.id if meeting is not None else None,
        source_type=source_type,
        filename=filename,
        file_size_bytes=max(file_size_bytes, 0),
        source_uri=source_uri,
        title=(title or "")[:200],
        follow_up_question=follow_up_question.strip(),
        status="queued",
        current_step="ingestion_event",
    )
    db.add(job)
    db.flush()
    enqueue_event(
        db,
        TOPIC_MEETING_UPLOADED,
        actor_user_id=user_id,
        job_id=job.job_id,
        meeting_id=job.meeting_id,
        resource_type="meeting",
        resource_id=job.meeting_id,
        payload={
            "source_type": source_type,
            "filename": filename,
            "file_size_bytes": max(file_size_bytes, 0),
            "has_transcript": source_type == "transcript",
        },
        key=job.job_id,
    )
    db.commit()
    db.refresh(job)
    increment_counter("pipeline.jobs.created")
    return job


def create_transcription_job(
    db: Session,
    user_id: int,
    job_id: str | None = None,
    filename: str = "",
    file_size_bytes: int = 0,
    source_uri: str = "",
) -> IngestionJob:
    job_id = job_id or new_job_id()
    job = IngestionJob(
        job_id=job_id,
        user_id=user_id,
        meeting_id=None,
        source_type=TRANSCRIPTION_JOB_SOURCE_TYPE,
        filename=filename,
        file_size_bytes=max(file_size_bytes, 0),
        source_uri=source_uri,
        title="",
        follow_up_question="",
        status="queued",
        current_step="transcription_queued",
    )
    db.add(job)
    db.flush()
    enqueue_event(
        db,
        TOPIC_TRANSCRIPTION_REQUESTED,
        actor_user_id=user_id,
        job_id=job.job_id,
        resource_type="transcription",
        resource_id=job.job_id,
        payload={"filename": filename, "file_size_bytes": max(file_size_bytes, 0)},
        key=job.job_id,
    )
    db.commit()
    db.refresh(job)
    increment_counter("pipeline.transcription_jobs.created")
    return job


def get_job(db: Session, job_id: str, for_update: bool = False) -> IngestionJob:
    statement = select(IngestionJob).where(IngestionJob.job_id == job_id)
    if for_update:
        statement = statement.with_for_update()
    job = db.scalar(statement)
    if job is None:
        raise LookupError("Job not found")
    return job


def get_job_for_user(db: Session, job_id: str, user_id: int, user_role: str) -> IngestionJob:
    job = get_job(db, job_id)
    if job.user_id != user_id:
        raise LookupError("Job not found")
    return job


def latest_transcription_job_for_user(db: Session, user_id: int, user_role: str) -> IngestionJob | None:
    statement = select(IngestionJob).where(
        IngestionJob.source_type == TRANSCRIPTION_JOB_SOURCE_TYPE,
        IngestionJob.user_id == user_id,
    )
    return db.scalar(statement.order_by(IngestionJob.created_at.desc(), IngestionJob.id.desc()).limit(1))


def list_failed_jobs(db: Session, user_id: int | None = None, limit: int = 10) -> list[IngestionJob]:
    statement = select(IngestionJob).where(IngestionJob.status == "failed")
    if user_id is not None:
        statement = statement.where(IngestionJob.user_id == user_id)
    return list(db.scalars(statement.order_by(IngestionJob.updated_at.desc(), IngestionJob.id.desc()).limit(limit)))


def update_job(
    db: Session,
    job: IngestionJob,
    status: str | None = None,
    current_step: str | None = None,
    meeting_id: int | None = None,
    error_message: str | None = None,
) -> IngestionJob:
    if status is not None:
        job.status = status
    if current_step is not None:
        job.current_step = current_step
    if meeting_id is not None:
        job.meeting_id = meeting_id
    if error_message is not None:
        job.error_message = error_message[:2000]
    job.updated_at = utc_now()
    db.flush()
    return job


def record_worker_heartbeat(
    db: Session,
    worker_id: str,
    display_name: str = "",
    hostname: str = "",
    mode: str = "kafka",
    status: str = "idle",
    current_topic: str = "",
    current_job_id: str = "",
    current_event_type: str = "",
    last_error: str = "",
    processed_delta: int = 0,
    failed_delta: int = 0,
) -> WorkerHeartbeat:
    now = utc_now()
    processed_increment = max(int(processed_delta or 0), 0)
    failed_increment = max(int(failed_delta or 0), 0)
    worker = db.scalar(select(WorkerHeartbeat).where(WorkerHeartbeat.worker_id == worker_id))
    if worker is None:
        worker = WorkerHeartbeat(
            worker_id=worker_id,
            display_name=display_name or worker_id,
            hostname=hostname,
            mode=mode,
            status=status,
            current_topic=current_topic,
            current_job_id=current_job_id,
            current_event_type=current_event_type,
            processed_count=0,
            failed_count=0,
            last_error=last_error[:1000] if last_error else "",
            started_at=now,
            last_seen_at=now,
            updated_at=now,
        )
        db.add(worker)

    worker.display_name = display_name or worker.display_name or worker_id
    worker.hostname = hostname or worker.hostname
    worker.mode = mode
    worker.status = status
    worker.current_topic = current_topic
    worker.current_job_id = current_job_id
    worker.current_event_type = current_event_type
    if last_error:
        worker.last_error = last_error[:1000]
    elif status == "processing":
        worker.last_error = ""
    worker.processed_count = (worker.processed_count or 0) + processed_increment
    worker.failed_count = (worker.failed_count or 0) + failed_increment
    worker.last_seen_at = now
    worker.updated_at = now
    db.flush()
    prune_worker_heartbeats(db, worker_id)
    return worker


def enqueue_analysis_requested(db: Session, job: IngestionJob) -> None:
    update_job(db, job, status="queued", current_step="analysis_job_queued")
    enqueue_event(
        db,
        TOPIC_TRANSCRIPT_TRANSCRIBED,
        actor_user_id=job.user_id,
        job_id=job.job_id,
        meeting_id=job.meeting_id,
        resource_type="transcript",
        resource_id=job.meeting_id,
        payload={"source_type": job.source_type, "transcript_stored": bool(job.meeting_id)},
        key=job.job_id,
    )
    enqueue_event(
        db,
        TOPIC_ANALYSIS_REQUESTED,
        actor_user_id=job.user_id,
        job_id=job.job_id,
        meeting_id=job.meeting_id,
        resource_type="meeting",
        resource_id=job.meeting_id,
        payload={"reason": "ingestion_ready"},
        key=job.job_id,
    )


def enqueue_transcription_requested(db: Session, job: IngestionJob) -> None:
    update_job(db, job, status="queued", current_step="transcription_queued")
    enqueue_event(
        db,
        TOPIC_TRANSCRIPTION_REQUESTED,
        actor_user_id=job.user_id,
        job_id=job.job_id,
        meeting_id=job.meeting_id,
        resource_type="transcription",
        resource_id=job.job_id,
        payload={"source_type": job.source_type, "filename": job.filename},
        key=job.job_id,
    )


def process_meeting_uploaded(db: Session, envelope: dict[str, Any]) -> None:
    job_id = str(envelope.get("job_id") or "")
    job = get_job(db, job_id, for_update=True)
    if job.status != "queued" or job.current_step != "ingestion_event":
        return

    if job.source_type == "transcript":
        update_job(db, job, status="processing", current_step="transcript_stored")
        enqueue_analysis_requested(db, job)
        db.commit()
        return

    if job.source_type in {"audio", "docx"}:
        if not job.source_uri:
            raise ValueError("Uploaded file path is missing")
        enqueue_transcription_requested(db, job)
        db.commit()
        return

    raise ValueError(f"Unsupported source type: {job.source_type}")


def process_transcription_requested(db: Session, envelope: dict[str, Any]) -> None:
    job_id = str(envelope.get("job_id") or "")
    job = get_job(db, job_id, for_update=True)
    if job.status != "queued" or job.current_step != "transcription_queued":
        return
    if job.source_type not in {TRANSCRIPTION_JOB_SOURCE_TYPE, "audio", "docx"}:
        raise ValueError("Transcription job has an invalid source type")
    if not job.source_uri:
        raise ValueError("Uploaded file path is missing")

    step = "extracting_transcript" if job.source_type == "docx" else "transcribing"
    update_job(db, job, status="processing", current_step=step, error_message="")
    db.commit()
    try:
        with Path(job.source_uri).open("rb") as file:
            if job.source_type == "docx":
                transcript = extract_docx_transcript(file, job.filename)
            else:
                transcript = transcribe_audio(file, job.filename)
    except Exception as exc:
        db.rollback()
        job = get_job(db, job_id)
        update_job(db, job, status="failed", current_step="transcription_failed", error_message=str(exc))
        enqueue_event(
            db,
            TOPIC_TRANSCRIPTION_FAILED,
            actor_user_id=job.user_id,
            job_id=job.job_id,
            resource_type="transcription",
            resource_id=job.job_id,
            payload={"error_type": type(exc).__name__},
            key=job.job_id,
        )
        db.commit()
        raise

    job = get_job(db, job_id)
    if job.source_type == TRANSCRIPTION_JOB_SOURCE_TYPE:
        write_transcription_result(job.job_id, transcript)
        update_job(db, job, status="completed", current_step="transcription_completed", error_message="")
        enqueue_event(
            db,
            TOPIC_TRANSCRIPT_TRANSCRIBED,
            actor_user_id=job.user_id,
            job_id=job.job_id,
            resource_type="transcription",
            resource_id=job.job_id,
            payload={"transcript_ready": True, "filename": job.filename},
            key=job.job_id,
        )
    else:
        meeting = create_meeting_stub(db, job.user_id, transcript, job.title, job.follow_up_question)
        update_job(db, job, status="queued", current_step="transcript_stored", meeting_id=meeting.id, error_message="")
        enqueue_analysis_requested(db, job)
    db.commit()


def process_analysis_requested(db: Session, envelope: dict[str, Any]) -> None:
    job_id = str(envelope.get("job_id") or "")
    job = get_job(db, job_id, for_update=True)
    if job.status != "queued" or job.current_step not in {"analysis_job_queued", "transcript_stored"}:
        return
    if not job.meeting_id:
        raise ValueError("Analysis job is missing meeting_id")
    meeting = db.get(Meeting, job.meeting_id)
    if meeting is None:
        raise LookupError("Meeting not found")

    update_job(db, job, status="processing", current_step="analysis_running")
    db.commit()
    try:
        analyzed = analyze_meeting_record(
            db,
            meeting,
            follow_up_question=job.follow_up_question,
            user_id=job.user_id,
        )
    except Exception as exc:
        db.rollback()
        job = get_job(db, job_id)
        update_job(db, job, status="failed", current_step="analysis_failed", error_message=str(exc))
        enqueue_event(
            db,
            TOPIC_ANALYSIS_FAILED,
            actor_user_id=job.user_id,
            job_id=job.job_id,
            meeting_id=job.meeting_id,
            resource_type="meeting",
            resource_id=job.meeting_id,
            payload={"error_type": type(exc).__name__},
            key=job.job_id,
        )
        db.commit()
        raise

    job = get_job(db, job_id)
    update_job(db, job, status="processing", current_step="embeddings_created", meeting_id=analyzed.id)
    enqueue_event(
        db,
        TOPIC_EMBEDDINGS_CREATED,
        actor_user_id=job.user_id,
        job_id=job.job_id,
        meeting_id=analyzed.id,
        resource_type="meeting",
        resource_id=analyzed.id,
        payload={
            "embedding_model": analyzed.embedding_model,
            "chunking_version": analyzed.chunking_version,
            "embedding_status": analyzed.embedding_status,
        },
        key=job.job_id,
    )
    update_job(db, job, status="completed", current_step="analysis_completed", meeting_id=analyzed.id, error_message="")
    enqueue_event(
        db,
        TOPIC_ANALYSIS_COMPLETED,
        actor_user_id=job.user_id,
        job_id=job.job_id,
        meeting_id=analyzed.id,
        resource_type="meeting",
        resource_id=analyzed.id,
        payload={"meeting_id": analyzed.id},
        key=job.job_id,
    )
    db.commit()


def process_event_envelope(db: Session, envelope: dict[str, Any]) -> None:
    event_type = str(envelope.get("event_type") or "")
    if event_type == TOPIC_MEETING_UPLOADED:
        process_meeting_uploaded(db, envelope)
    elif event_type == TOPIC_TRANSCRIPTION_REQUESTED:
        process_transcription_requested(db, envelope)
    elif event_type == TOPIC_ANALYSIS_REQUESTED:
        process_analysis_requested(db, envelope)


def process_outbox_once(db: Session, limit: int = 20) -> int:
    events = list(
        db.scalars(
            select(EventOutbox)
            .where(
                EventOutbox.publish_status.in_(("pending", "published", "failed")),
                EventOutbox.event_type.in_(
                    (TOPIC_MEETING_UPLOADED, TOPIC_TRANSCRIPTION_REQUESTED, TOPIC_ANALYSIS_REQUESTED)
                ),
            )
            .order_by(EventOutbox.created_at.asc(), EventOutbox.id.asc())
            .limit(limit)
        )
    )
    processed = 0
    for event in events:
        envelope = json.loads(event.envelope_json)
        try:
            process_event_envelope(db, envelope)
        except Exception as exc:
            db.rollback()
            event = db.get(EventOutbox, event.id)
            if event is not None:
                event.last_error = str(exc)[:1000]
                event.publish_status = "processed"
        else:
            event.publish_status = "processed"
        processed += 1
        db.commit()
    return processed


def queued_job_event_details(job: IngestionJob) -> dict[str, Any] | None:
    if job.current_step == "ingestion_event":
        return {
            "event_type": TOPIC_MEETING_UPLOADED,
            "resource_type": "meeting",
            "resource_id": job.meeting_id,
            "payload": {
                "source_type": job.source_type,
                "filename": job.filename,
                "file_size_bytes": max(job.file_size_bytes, 0),
                "has_transcript": job.source_type == "transcript",
                "reason": "queued_recovery",
            },
        }
    if job.current_step == "transcription_queued":
        return {
            "event_type": TOPIC_TRANSCRIPTION_REQUESTED,
            "resource_type": "transcription",
            "resource_id": job.job_id,
            "payload": {
                "source_type": job.source_type,
                "filename": job.filename,
                "reason": "queued_recovery",
            },
        }
    if job.current_step in {"analysis_job_queued", "transcript_stored"} and job.meeting_id:
        return {
            "event_type": TOPIC_ANALYSIS_REQUESTED,
            "resource_type": "meeting",
            "resource_id": job.meeting_id,
            "payload": {"reason": "queued_recovery"},
        }
    return None


def process_stale_queued_jobs_once(
    db: Session,
    stale_after_seconds: int = QUEUE_RECOVERY_AFTER_SECONDS,
    limit: int = 5,
) -> int:
    cutoff = utc_now() - timedelta(seconds=max(stale_after_seconds, 1))
    jobs = list(
        db.scalars(
            select(IngestionJob)
            .where(IngestionJob.status == "queued", IngestionJob.updated_at <= cutoff)
            .order_by(IngestionJob.updated_at.asc(), IngestionJob.id.asc())
            .limit(limit)
        )
    )
    processed = 0
    for job in jobs:
        event_details = queued_job_event_details(job)
        if event_details is None:
            continue

        event = db.scalar(
            select(EventOutbox)
            .where(
                EventOutbox.key == job.job_id,
                EventOutbox.event_type == event_details["event_type"],
                EventOutbox.publish_status.in_(("pending", "published", "failed")),
            )
            .order_by(EventOutbox.created_at.desc(), EventOutbox.id.desc())
            .limit(1)
        )
        if event is None:
            event = enqueue_event(
                db,
                event_details["event_type"],
                actor_user_id=job.user_id,
                job_id=job.job_id,
                meeting_id=job.meeting_id,
                resource_type=event_details["resource_type"],
                resource_id=event_details["resource_id"],
                payload=event_details["payload"],
                key=job.job_id,
            )
            db.flush()
        elif datetime_after(event.created_at, cutoff):
            continue

        try:
            process_event_envelope(db, json.loads(event.envelope_json))
        except Exception as exc:
            db.rollback()
            event = db.get(EventOutbox, event.id)
            if event is not None:
                event.last_error = str(exc)[:1000]
                event.publish_status = "processed"
        else:
            event.publish_status = "processed"
        processed += 1
        db.commit()
    return processed


def job_event_envelopes(db: Session, job_id: str, after_id: int = 0) -> list[tuple[int, dict[str, Any]]]:
    events = list(
        db.scalars(
            select(EventOutbox)
            .where(EventOutbox.key == job_id, EventOutbox.id > after_id)
            .order_by(EventOutbox.id.asc())
        )
    )
    return [(event.id, json.loads(event.envelope_json)) for event in events]


def worker_heartbeat_to_dict(worker: WorkerHeartbeat) -> dict[str, Any]:
    now = utc_now()
    last_seen_age = seconds_between(now, worker.last_seen_at)
    effective_status = worker.status
    if last_seen_age > WORKER_STALE_AFTER_SECONDS:
        effective_status = "stale"
    return {
        "id": worker.id,
        "worker_id": worker.worker_id,
        "display_name": worker.display_name,
        "hostname": worker.hostname,
        "mode": worker.mode,
        "status": effective_status,
        "current_topic": worker.current_topic,
        "current_job_id": worker.current_job_id,
        "current_event_type": worker.current_event_type,
        "processed_count": worker.processed_count,
        "failed_count": worker.failed_count,
        "last_error": worker.last_error,
        "started_at": worker.started_at,
        "last_seen_at": worker.last_seen_at,
        "seconds_since_seen": last_seen_age,
    }


def missing_worker_to_dict(index: int) -> dict[str, Any]:
    now = utc_now()
    return {
        "id": 0 - index,
        "worker_id": f"missing-worker:{index}",
        "display_name": f"backend-worker {index}",
        "hostname": "",
        "mode": "",
        "status": "missing",
        "current_topic": "",
        "current_job_id": "",
        "current_event_type": "",
        "processed_count": 0,
        "failed_count": 0,
        "last_error": "",
        "started_at": now,
        "last_seen_at": now,
        "seconds_since_seen": 0,
    }


def pipeline_operations_summary(db: Session) -> dict[str, Any]:
    job_count_statement = select(IngestionJob.status, func.count(IngestionJob.id)).group_by(IngestionJob.status)
    job_counts = {
        status: count
        for status, count in db.execute(job_count_statement).all()
    }
    failed_job_count = int(
        db.scalar(select(func.count(IngestionJob.id)).where(IngestionJob.status == "failed")) or 0
    )
    topic_rows = db.execute(
        select(EventOutbox.topic, EventOutbox.publish_status, func.count(EventOutbox.id)).group_by(
            EventOutbox.topic,
            EventOutbox.publish_status,
        )
    ).all()
    topic_metrics: dict[str, dict[str, Any]] = {}
    for topic, status, count in topic_rows:
        topic_metrics.setdefault(topic, {"topic": topic, "pending": 0, "published": 0, "failed": 0, "processed": 0})
        if status in {"pending", "published", "failed", "processed"}:
            topic_metrics[topic][status] = int(count)

    workers = list(
        db.scalars(
            select(WorkerHeartbeat).order_by(
                WorkerHeartbeat.last_seen_at.desc(),
                WorkerHeartbeat.id.desc(),
            )
        )
    )
    all_worker_payloads = [worker_heartbeat_to_dict(worker) for worker in workers]
    active_worker_payloads = [worker for worker in all_worker_payloads if worker["status"] not in {"stale", "missing"}]
    stale_worker_payloads = [worker for worker in all_worker_payloads if worker["status"] == "stale"]

    if EXPECTED_WORKER_COUNT:
        worker_payloads = active_worker_payloads[:EXPECTED_WORKER_COUNT]
        open_slots = max(EXPECTED_WORKER_COUNT - len(worker_payloads), 0)
        worker_payloads.extend(stale_worker_payloads[:open_slots])
    else:
        worker_payloads = all_worker_payloads

    reporting_worker_count = sum(1 for worker in worker_payloads if worker["status"] not in {"stale", "missing"})
    stale_worker_count = sum(1 for worker in worker_payloads if worker["status"] == "stale")
    missing_worker_count = max(EXPECTED_WORKER_COUNT - len(worker_payloads), 0)
    worker_payloads.extend(
        missing_worker_to_dict(index) for index in range(len(worker_payloads) + 1, EXPECTED_WORKER_COUNT + 1)
    )

    return {
        "expected_worker_count": EXPECTED_WORKER_COUNT,
        "reporting_worker_count": reporting_worker_count,
        "missing_worker_count": missing_worker_count,
        "stale_worker_count": stale_worker_count,
        "job_counts": {key: int(value) for key, value in job_counts.items()},
        "workers": worker_payloads,
        "kafka_topics": list(topic_metrics.values()),
        "failed_job_count": failed_job_count,
        "failed_jobs": [job_to_dict(job) for job in list_failed_jobs(db)],
    }


def durable_analysis_latency_summary(db: Session) -> dict[str, float | int] | None:
    completed_latency = Meeting.generation_latency_ms > 0
    count, average_ms, max_ms = db.execute(
        select(
            func.count(Meeting.id),
            func.avg(Meeting.generation_latency_ms),
            func.max(Meeting.generation_latency_ms),
        ).where(completed_latency)
    ).one()
    if not count:
        return None

    latest_ms = db.scalar(
        select(Meeting.generation_latency_ms)
        .where(completed_latency)
        .order_by(Meeting.updated_at.desc(), Meeting.id.desc())
        .limit(1)
    )
    return {
        "count": int(count),
        "average_seconds": float(average_ms or 0) / 1000,
        "max_seconds": float(max_ms or 0) / 1000,
        "latest_seconds": float(latest_ms or 0) / 1000,
    }
