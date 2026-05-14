from fastapi import Depends, FastAPI, File, HTTPException, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
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
from .database import get_db, init_db
from .exports import build_transcript_docx
from .llm import transcribe_audio
from .models import User
from .schemas import (
    ActionCreate,
    ActionRead,
    ActionUpdate,
    AnalyzeResponse,
    AuthResponse,
    MeetingAnalyzeRequest,
    MeetingListItem,
    MeetingRead,
    MeetingUpdate,
    UserCreate,
    UserLogin,
    UserRead,
)
from .services import (
    action_to_dict,
    add_action,
    create_meeting_from_analysis,
    delete_action,
    delete_meeting,
    export_meeting_report,
    get_meeting,
    list_meetings,
    meeting_list_item,
    meeting_to_dict,
    update_action,
    update_meeting,
)


app = FastAPI(title="AI Meeting Action Agent API")
security = HTTPBearer(auto_error=False)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    db = next(get_db())
    try:
        ensure_demo_user(db)
    finally:
        db.close()


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


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/auth/register", response_model=AuthResponse)
def register(request: UserCreate, db: Session = Depends(get_db)) -> dict:
    try:
        user = create_user(db, request.email, request.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "access_token": create_access_token(user.id),
        "token_type": "bearer",
        "user": user_to_dict(user),
    }


@app.post("/api/auth/login", response_model=AuthResponse)
def login(request: UserLogin, db: Session = Depends(get_db)) -> dict:
    user = authenticate_user(db, request.email, request.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    return {
        "access_token": create_access_token(user.id),
        "token_type": "bearer",
        "user": user_to_dict(user),
    }


@app.post("/api/auth/demo", response_model=AuthResponse)
def demo_login(db: Session = Depends(get_db)) -> dict:
    user = ensure_demo_user(db)
    return {
        "access_token": create_access_token(user.id),
        "token_type": "bearer",
        "user": user_to_dict(user),
    }


@app.get("/api/auth/me", response_model=UserRead)
def me(user: User = Depends(current_user)) -> dict:
    return user_to_dict(user)


@app.post("/api/meetings/transcribe")
async def transcribe_meeting_audio(
    file: UploadFile = File(...),
    user: User = Depends(current_user),
) -> dict[str, str]:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Audio filename is required")

    try:
        transcript = await run_in_threadpool(transcribe_audio, file.file, file.filename)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        await file.close()

    return {"transcript": transcript}


@app.post("/api/meetings/analyze", response_model=AnalyzeResponse)
def analyze_meeting(
    request: MeetingAnalyzeRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    try:
        meeting = create_meeting_from_analysis(db, request, user_id=user.id)
        return meeting_to_dict(meeting)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/meetings", response_model=list[MeetingListItem])
def meetings(db: Session = Depends(get_db), user: User = Depends(current_user)) -> list[dict]:
    return [meeting_list_item(meeting) for meeting in list_meetings(db, user_id=user.id)]


@app.get("/api/meetings/{meeting_id}", response_model=MeetingRead)
def meeting_detail(meeting_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    try:
        return meeting_to_dict(get_meeting(db, meeting_id, user_id=user.id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.patch("/api/meetings/{meeting_id}", response_model=MeetingRead)
def patch_meeting(
    meeting_id: int,
    update: MeetingUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    try:
        return meeting_to_dict(update_meeting(db, meeting_id, update, user_id=user.id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/meetings/{meeting_id}/actions", response_model=ActionRead)
def create_action(
    meeting_id: int,
    action: ActionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    try:
        return action_to_dict(add_action(db, meeting_id, action, user_id=user.id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.patch("/api/actions/{action_id}", response_model=ActionRead)
def patch_action(
    action_id: int,
    update: ActionUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    try:
        return action_to_dict(update_action(db, action_id, update, user_id=user.id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/actions/{action_id}", status_code=204)
def remove_action(action_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> Response:
    try:
        delete_action(db, action_id, user_id=user.id)
        return Response(status_code=204)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/api/meetings/{meeting_id}", status_code=204)
def remove_meeting(meeting_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> Response:
    try:
        delete_meeting(db, meeting_id, user_id=user.id)
        return Response(status_code=204)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/meetings/{meeting_id}/export")
def export_report(meeting_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> StreamingResponse:
    try:
        report = export_meeting_report(db, meeting_id, user_id=user.id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    headers = {"Content-Disposition": f'attachment; filename="meeting_{meeting_id}_report.docx"'}
    return StreamingResponse(
        iter([report]),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers=headers,
    )


@app.get("/api/meetings/{meeting_id}/transcript")
def export_transcript(meeting_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> StreamingResponse:
    try:
        meeting = get_meeting(db, meeting_id, user_id=user.id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    transcript = build_transcript_docx(meeting.transcript)
    headers = {"Content-Disposition": f'attachment; filename="meeting_{meeting_id}_transcript.docx"'}
    return StreamingResponse(
        iter([transcript]),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers=headers,
    )
