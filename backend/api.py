import json
import logging
import os
import threading
import time
from collections import defaultdict, deque

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .auth import (
    authenticate_user,
    create_access_token,
    create_user,
    decode_access_token,
    ensure_demo_user,
    get_user_by_id,
    user_to_dict,
)
from .database import SessionLocal, engine, get_db, init_db
from .events import TOPIC_ACTION_UPDATED, enqueue_event, publish_pending_outbox
from .exports import build_transcript_docx
from .governance import safe_hash, sync_prompt_registry
from .models import User
from .observability import (
    configure_opentelemetry,
    increment_counter,
    log_event,
    metrics_snapshot,
    new_request_id,
    prometheus_metrics,
    record_http_request,
    set_request_id,
    timed_operation,
)
from .transcript_import import extract_docx_transcript
from .schemas import (
    ActionCreate,
    ActionRead,
    ActionUpdate,
    AuditEventPageRead,
    AiRunRead,
    AuthResponse,
    IngestResponse,
    IngestionJobRead,
    MeetingListItem,
    MeetingRead,
    MeetingUpdate,
    PipelineOperationsRead,
    PromptVersionRead,
    UserCreate,
    UserLogin,
    UserRead,
)
from .pipeline import (
    create_transcription_job,
    create_ingestion_job,
    durable_analysis_latency_summary,
    get_job_for_user,
    read_transcription_result,
    job_event_envelopes,
    job_to_dict,
    latest_transcription_job_for_user,
    new_job_id,
    pipeline_operations_summary,
    save_upload_bytes,
)
from .services import (
    action_to_dict,
    add_action,
    ai_run_to_dict,
    delete_action,
    delete_meeting,
    export_meeting_report,
    get_ai_run_for_user,
    get_meeting_for_user,
    audit_event_to_dict,
    count_audit_events,
    list_meetings_for_user,
    list_audit_events,
    list_prompt_version_dicts,
    meeting_list_item,
    meeting_to_dict,
    record_audit_event,
    update_action,
    update_meeting,
)


app = FastAPI(title="ai-meeting-action-agent API")
security = HTTPBearer(auto_error=False)
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))
MAX_TRANSCRIPT_CHARS = int(os.getenv("MAX_TRANSCRIPT_CHARS", "250000"))
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "120"))
DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_RATE_LOCK = threading.Lock()
_RATE_BUCKETS: defaultdict[str, deque[float]] = defaultdict(deque)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
configure_opentelemetry(app, engine=engine)


def route_path(request: Request) -> str:
    route = request.scope.get("route")
    return getattr(route, "path", request.url.path)


def request_ip_hash(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For", "").split(",", 1)[0].strip()
    client_host = request.client.host if request.client else ""
    return safe_hash(forwarded or client_host)


def request_user_agent_hash(request: Request) -> str:
    return safe_hash(request.headers.get("User-Agent", ""))


def audit_hashes(request: Request) -> dict[str, str]:
    return {
        "ip_hash": request_ip_hash(request),
        "user_agent_hash": request_user_agent_hash(request),
    }


def rate_limit_exceeded(request: Request) -> bool:
    if RATE_LIMIT_PER_MINUTE <= 0:
        return False
    key = f"{request.client.host if request.client else 'unknown'}:{route_path(request)}"
    now = time.monotonic()
    with _RATE_LOCK:
        bucket = _RATE_BUCKETS[key]
        while bucket and now - bucket[0] > 60:
            bucket.popleft()
        if len(bucket) >= RATE_LIMIT_PER_MINUTE:
            return True
        bucket.append(now)
    return False


@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or new_request_id()
    set_request_id(request_id)
    start = time.perf_counter()
    status_code = 500
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        content_length = int(request.headers.get("content-length") or 0)
        if content_length > MAX_UPLOAD_BYTES:
            return JSONResponse(
                status_code=413,
                content={"detail": f"Request body exceeds the {MAX_UPLOAD_BYTES} byte upload limit"},
                headers={"X-Request-ID": request_id},
            )
    if rate_limit_exceeded(request):
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded. Please retry shortly."},
            headers={"X-Request-ID": request_id},
        )
    try:
        response = await call_next(request)
        status_code = response.status_code
    except Exception as exc:
        elapsed = time.perf_counter() - start
        record_http_request(request.method, route_path(request), status_code, elapsed)
        log_event(
            logging.ERROR,
            "request_failed",
            method=request.method,
            path=route_path(request),
            status_code=status_code,
            elapsed_seconds=round(elapsed, 4),
            error_type=type(exc).__name__,
        )
        raise

    elapsed = time.perf_counter() - start
    response.headers["X-Request-ID"] = request_id
    record_http_request(request.method, route_path(request), status_code, elapsed)
    return response


def record_api_request(name: str) -> None:
    increment_counter("api.requests")
    increment_counter(f"api.{name}.requests")


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    db = next(get_db())
    try:
        demo_user = ensure_demo_user(db)
        sync_prompt_registry(db, created_by=demo_user.id)
    finally:
        db.close()
    log_event(20, "api_startup_complete", service="backend")


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Authentication required")

    user_id = decode_access_token(credentials.credentials)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user = get_user_by_id(db, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return user


def require_roles(user: User, *roles: str) -> None:
    if user.role not in set(roles):
        raise HTTPException(status_code=403, detail="Permission denied")


def audit_permission_denied(
    db: Session,
    user: User,
    request: Request,
    resource_type: str,
    resource_id: int | str | None = None,
    metadata: dict | None = None,
) -> None:
    record_audit_event(
        db,
        "permission.denied",
        user_id=user.id,
        entity_type=resource_type,
        entity_id=resource_id,
        status="denied",
        metadata=metadata or {"path": route_path(request)},
        **audit_hashes(request),
    )


def try_publish_outbox(db: Session) -> None:
    try:
        publish_pending_outbox(db, limit=25)
    except Exception as exc:
        log_event(logging.WARNING, "outbox_publish_deferred", error_type=type(exc).__name__)


def infer_source_type(filename: str, content_type: str | None) -> str:
    lowered = filename.lower()
    if lowered.endswith(".docx"):
        return "docx"
    if content_type and content_type.startswith("audio/"):
        return "audio"
    if lowered.endswith((".mp3", ".mp4", ".mpeg", ".mpga", ".m4a", ".wav", ".webm")):
        return "audio"
    raise HTTPException(status_code=400, detail="Upload must be an audio file or .docx transcript")


def sse_event(event_id: int, event_type: str, payload: dict) -> str:
    data = json.dumps(payload, ensure_ascii=False, default=str)
    return f"id: {event_id}\nevent: {event_type}\ndata: {data}\n\n"


def docx_response(content: bytes, filename: str) -> StreamingResponse:
    safe_filename = filename if filename.lower().endswith(".docx") else f"{filename}.docx"
    return StreamingResponse(
        iter([content]),
        media_type=DOCX_MEDIA_TYPE,
        headers={
            "Content-Disposition": f'attachment; filename="{safe_filename}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.get("/api/health")
def health() -> dict[str, str]:
    record_api_request("health")
    return {"status": "ok"}


@app.get("/api/metrics")
def metrics(db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    record_api_request("metrics")
    snapshot = metrics_snapshot()
    durable_latency = durable_analysis_latency_summary(db)
    if durable_latency is not None:
        snapshot["latencies"]["analysis.graph.run"] = durable_latency
    return snapshot


@app.get("/metrics")
def prometheus_endpoint() -> Response:
    data, media_type = prometheus_metrics()
    return Response(content=data, media_type=media_type)


@app.get("/governance/prompts", response_model=list[PromptVersionRead])
@app.get("/api/governance/prompts", response_model=list[PromptVersionRead])
def governance_prompts(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[dict[str, object]]:
    record_api_request("governance_prompts")
    require_roles(user, "admin")
    return list_prompt_version_dicts(db)


@app.get("/audit/events", response_model=AuditEventPageRead)
@app.get("/api/audit/events", response_model=AuditEventPageRead)
def audit_events(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    record_api_request("audit_events")
    total = count_audit_events(db, user=user)
    total_pages = max(1, (total + page_size - 1) // page_size)
    return {
        "items": [audit_event_to_dict(event, db=db) for event in list_audit_events(db, user=user, page=page, page_size=page_size)],
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
    }


@app.post("/api/auth/register", response_model=AuthResponse)
def register(request: UserCreate, http_request: Request, db: Session = Depends(get_db)) -> dict:
    record_api_request("auth_register")
    try:
        user = create_user(db, request.email, request.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    record_audit_event(db, "auth.register", user_id=user.id, entity_type="user", entity_id=user.id, **audit_hashes(http_request))

    return {
        "access_token": create_access_token(user.id),
        "token_type": "bearer",
        "user": user_to_dict(user),
    }


@app.post("/api/auth/login", response_model=AuthResponse)
def login(request: UserLogin, http_request: Request, db: Session = Depends(get_db)) -> dict:
    record_api_request("auth_login")
    user = authenticate_user(db, request.email, request.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    record_audit_event(db, "auth.login", user_id=user.id, entity_type="user", entity_id=user.id, **audit_hashes(http_request))
    return {
        "access_token": create_access_token(user.id),
        "token_type": "bearer",
        "user": user_to_dict(user),
    }


@app.post("/api/auth/demo", response_model=AuthResponse)
def demo_login(request: Request, db: Session = Depends(get_db)) -> dict:
    record_api_request("auth_demo")
    user = ensure_demo_user(db)
    record_audit_event(db, "auth.demo", user_id=user.id, entity_type="user", entity_id=user.id, **audit_hashes(request))
    return {
        "access_token": create_access_token(user.id),
        "token_type": "bearer",
        "user": user_to_dict(user),
    }


@app.get("/api/auth/me", response_model=UserRead)
def me(user: User = Depends(current_user)) -> dict:
    record_api_request("auth_me")
    return user_to_dict(user)


@app.post("/api/meetings/transcribe/jobs", response_model=IngestResponse)
async def queue_transcription_job(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    record_api_request("transcription_job_create")
    if not file.filename:
        raise HTTPException(status_code=400, detail="Audio filename is required")
    if infer_source_type(file.filename, file.content_type) != "audio":
        raise HTTPException(status_code=400, detail="Upload must be an audio file")

    job_id = new_job_id()
    content = await file.read()
    await file.close()
    source_uri = save_upload_bytes(job_id, file.filename, content)
    job = create_transcription_job(
        db,
        user_id=user.id,
        job_id=job_id,
        filename=file.filename,
        file_size_bytes=len(content),
        source_uri=source_uri,
    )
    record_audit_event(
        db,
        "meeting.transcription_job",
        user_id=user.id,
        entity_type="transcription",
        entity_id=job.job_id,
        metadata={"filename": job.filename},
        **audit_hashes(request),
    )
    try_publish_outbox(db)
    return {
        "job_id": job.job_id,
        "status": job.status,
        "meeting_id": None,
        "current_step": job.current_step,
        "file_size_bytes": job.file_size_bytes,
    }


@app.post("/api/meetings/import-transcript")
async def import_transcript_document(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, str]:
    record_api_request("import_transcript")
    if not file.filename:
        raise HTTPException(status_code=400, detail="DOCX filename is required")

    try:
        with timed_operation(
            "api.import_transcript",
            success_counter="transcript_import.success",
            failure_counter="transcript_import.failure",
            user_id=user.id,
        ):
            transcript = await run_in_threadpool(extract_docx_transcript, file.file, file.filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        await file.close()

    record_audit_event(
        db=db,
        event_type="meeting.import_transcript",
        user_id=user.id,
        entity_type="transcript",
        metadata={"filename": file.filename},
        **audit_hashes(request),
    )
    return {"transcript": transcript}


@app.post("/api/meetings/ingest", response_model=IngestResponse)
async def ingest_meeting(
    request: Request,
    file: UploadFile | None = File(None),
    transcript: str | None = Form(None),
    title: str | None = Form(None),
    follow_up_question: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    record_api_request("meeting_ingest")
    if file is None and not (transcript or "").strip():
        raise HTTPException(status_code=400, detail="Provide an audio file, DOCX transcript, or transcript text")

    job_id = new_job_id()
    if file is not None:
        if not file.filename:
            raise HTTPException(status_code=400, detail="Upload filename is required")
        source_type = infer_source_type(file.filename, file.content_type)
        content = await file.read()
        await file.close()
        source_uri = save_upload_bytes(job_id, file.filename, content)
        job = create_ingestion_job(
            db,
            user_id=user.id,
            source_type=source_type,
            job_id=job_id,
            title=title,
            follow_up_question=follow_up_question,
            filename=file.filename,
            file_size_bytes=len(content),
            source_uri=source_uri,
        )
    else:
        transcript_text = (transcript or "").strip()
        if len(transcript_text) > MAX_TRANSCRIPT_CHARS:
            raise HTTPException(status_code=413, detail=f"Transcript exceeds the {MAX_TRANSCRIPT_CHARS} character limit")
        job = create_ingestion_job(
            db,
            user_id=user.id,
            source_type="transcript",
            job_id=job_id,
            title=title,
            follow_up_question=follow_up_question,
            filename="inline-transcript.txt",
            transcript=transcript_text,
        )

    record_audit_event(
        db,
        "meeting.ingest",
        user_id=user.id,
        entity_type="ingestion_job",
        entity_id=job.job_id,
        metadata={
            "source_type": job.source_type,
            "meeting_id": job.meeting_id,
            "filename": job.filename,
            "file_size_bytes": job.file_size_bytes,
        },
        **audit_hashes(request),
    )
    try_publish_outbox(db)
    return {
        "job_id": job.job_id,
        "status": job.status,
        "meeting_id": job.meeting_id,
        "current_step": job.current_step,
        "file_size_bytes": job.file_size_bytes,
    }


@app.get("/api/jobs/latest/transcription", response_model=IngestionJobRead | None)
def latest_transcription_job(db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict | None:
    record_api_request("latest_transcription_job")
    job = latest_transcription_job_for_user(db, user.id, user.role)
    return job_to_dict(job) if job is not None else None


@app.get("/api/jobs/{job_id}", response_model=IngestionJobRead)
def job_detail(job_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    record_api_request("job_detail")
    try:
        return job_to_dict(get_job_for_user(db, job_id, user.id, user.role))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc


@app.get("/api/jobs/{job_id}/events")
def job_events(job_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> StreamingResponse:
    record_api_request("job_events")
    try:
        get_job_for_user(db, job_id, user.id, user.role)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc

    def event_stream():
        last_id = 0
        while True:
            stream_db = SessionLocal()
            try:
                job = get_job_for_user(stream_db, job_id, user.id, user.role)
                for event_id, envelope in job_event_envelopes(stream_db, job_id, after_id=last_id):
                    last_id = event_id
                    yield sse_event(
                        event_id,
                        str(envelope.get("event_type") or "pipeline.event"),
                        {"job": job_to_dict(job), "event": envelope},
                    )
                yield sse_event(last_id, "job.status", {"job": job_to_dict(job)})
                if job.status in {"completed", "failed"}:
                    break
            finally:
                stream_db.close()
            time.sleep(1)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/jobs/{job_id}/transcript")
def job_transcript(job_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, str]:
    record_api_request("job_transcript")
    try:
        job = get_job_for_user(db, job_id, user.id, user.role)
        return {"transcript": read_transcription_result(job)}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc


@app.get("/api/operations/pipeline", response_model=PipelineOperationsRead)
def pipeline_operations(db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    record_api_request("pipeline_operations")
    require_roles(user, "admin")
    return pipeline_operations_summary(db)


@app.get("/api/meetings", response_model=list[MeetingListItem])
def meetings(db: Session = Depends(get_db), user: User = Depends(current_user)) -> list[dict]:
    record_api_request("meetings_list")
    return [meeting_list_item(meeting) for meeting in list_meetings_for_user(db, user)]


@app.get("/api/meetings/{meeting_id}", response_model=MeetingRead)
def meeting_detail(
    meeting_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    record_api_request("meeting_detail")
    try:
        meeting = get_meeting_for_user(db, meeting_id, user)
        return meeting_to_dict(meeting)
    except LookupError as exc:
        audit_permission_denied(db, user, request, "meeting", meeting_id)
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.patch("/api/meetings/{meeting_id}", response_model=MeetingRead)
def patch_meeting(
    meeting_id: int,
    update: MeetingUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    record_api_request("meeting_update")
    try:
        payload = meeting_to_dict(update_meeting(db, meeting_id, update, user_id=user.id))
        record_audit_event(
            db,
            "meeting.update",
            user_id=user.id,
            entity_type="meeting",
            entity_id=meeting_id,
            **audit_hashes(request),
        )
        return payload
    except LookupError as exc:
        audit_permission_denied(db, user, request, "meeting", meeting_id)
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/meetings/{meeting_id}/actions", response_model=ActionRead)
def create_action(
    meeting_id: int,
    action: ActionCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    record_api_request("action_create")
    try:
        payload = action_to_dict(add_action(db, meeting_id, action, user_id=user.id))
        record_audit_event(
            db,
            "action.create",
            user_id=user.id,
            entity_type="action",
            entity_id=payload["id"],
            metadata={"meeting_id": meeting_id, "status": payload["status"]},
            **audit_hashes(request),
        )
        return payload
    except LookupError as exc:
        audit_permission_denied(db, user, request, "meeting", meeting_id)
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.patch("/api/actions/{action_id}", response_model=ActionRead)
def patch_action(
    action_id: int,
    update: ActionUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    record_api_request("action_update")
    try:
        payload = action_to_dict(update_action(db, action_id, update, user_id=user.id))
        record_audit_event(
            db,
            "action.update",
            user_id=user.id,
            entity_type="action",
            entity_id=action_id,
            metadata={
                "meeting_id": payload["meeting_id"],
                "status": payload["status"],
            },
            **audit_hashes(request),
        )
        enqueue_event(
            db,
            TOPIC_ACTION_UPDATED,
            actor_user_id=user.id,
            meeting_id=payload["meeting_id"],
            resource_type="action",
            resource_id=action_id,
            payload={"status": payload["status"]},
            key=f"meeting-{payload['meeting_id']}",
        )
        db.commit()
        try_publish_outbox(db)
        return payload
    except LookupError as exc:
        audit_permission_denied(db, user, request, "action", action_id)
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/actions/{action_id}", status_code=204)
def remove_action(
    action_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Response:
    record_api_request("action_delete")
    try:
        delete_action(db, action_id, user_id=user.id)
        record_audit_event(
            db,
            "action.delete",
            user_id=user.id,
            entity_type="action",
            entity_id=action_id,
            **audit_hashes(request),
        )
        return Response(status_code=204)
    except LookupError as exc:
        audit_permission_denied(db, user, request, "action", action_id)
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/api/meetings/{meeting_id}", status_code=204)
def remove_meeting(
    meeting_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Response:
    record_api_request("meeting_delete")
    try:
        delete_meeting(db, meeting_id, user_id=user.id)
        record_audit_event(
            db,
            "meeting.delete",
            user_id=user.id,
            entity_type="meeting",
            entity_id=meeting_id,
            **audit_hashes(request),
        )
        return Response(status_code=204)
    except LookupError as exc:
        audit_permission_denied(db, user, request, "meeting", meeting_id)
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/meetings/{meeting_id}/export")
def export_report(
    meeting_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> StreamingResponse:
    record_api_request("export_report")
    try:
        with timed_operation(
            "api.export_report",
            success_counter="exports.report.success",
            failure_counter="exports.report.failure",
            user_id=user.id,
            meeting_id=meeting_id,
        ):
            report = export_meeting_report(db, meeting_id, user_id=user.id)
    except LookupError as exc:
        audit_permission_denied(db, user, request, "meeting", meeting_id)
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    record_audit_event(
        db,
        "meeting.export_report",
        user_id=user.id,
        entity_type="meeting",
        entity_id=meeting_id,
        **audit_hashes(request),
    )
    return docx_response(report, f"meeting_{meeting_id}_report.docx")


@app.get("/api/meetings/{meeting_id}/transcript")
def export_transcript(
    meeting_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> StreamingResponse:
    record_api_request("export_transcript")
    try:
        with timed_operation(
            "api.export_transcript",
            success_counter="exports.transcript.success",
            failure_counter="exports.transcript.failure",
            user_id=user.id,
            meeting_id=meeting_id,
        ):
            meeting = get_meeting_for_user(db, meeting_id, user, require_raw_transcript=True)
    except LookupError as exc:
        audit_permission_denied(db, user, request, "meeting", meeting_id)
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    transcript = build_transcript_docx(meeting.transcript)
    record_audit_event(
        db,
        "meeting.export_transcript",
        user_id=user.id,
        entity_type="meeting",
        entity_id=meeting_id,
        **audit_hashes(request),
    )
    return docx_response(transcript, f"meeting_{meeting_id}_transcript.docx")


@app.get("/ai/runs/{run_id}", response_model=AiRunRead)
@app.get("/api/ai/runs/{run_id}", response_model=AiRunRead)
def ai_run_detail(
    run_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    record_api_request("ai_run_detail")
    try:
        return ai_run_to_dict(get_ai_run_for_user(db, run_id, user))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Run ID invalid or not found.") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail="Run ID invalid or not found.") from exc
