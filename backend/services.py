import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .action_agent import run_action_agent
from .exports import build_agent_report_docx
from .llm import answer_follow_up_question, summarize_transcript, summary_to_markdown
from .models import ActionItem, Meeting
from .schemas import ActionCreate, ActionUpdate, MeetingAnalyzeRequest, MeetingUpdate
from .transcript_processing import process_transcript


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
    summary_engine: str = "gpt",
) -> dict[str, Any]:
    cleaning = process_transcript(transcript)

    if summary_engine == "local":
        from .local_model import summarize_with_local_model

        summary = summarize_with_local_model(cleaning.cleaned_text)
    else:
        summary = summarize_transcript(cleaning.cleaned_text, follow_up_question=follow_up_question)

    summary_markdown = summary_to_markdown(summary)

    return {
        "transcript": transcript,
        "cleaned_transcript": cleaning.cleaned_text,
        "summary": summary,
        "summary_markdown": summary_markdown,
    }


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
        "created_at": action.created_at,
        "updated_at": action.updated_at,
    }


def meeting_to_dict(meeting: Meeting) -> dict[str, Any]:
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


def create_meeting_from_analysis(
    db: Session,
    request: MeetingAnalyzeRequest,
    user_id: int | None = None,
) -> Meeting:
    analysis = build_analysis(
        transcript=request.transcript,
        follow_up_question=request.follow_up_question,
        summary_engine=request.summary_engine,
    )
    meeting = Meeting(
        user_id=user_id,
        title=make_title(request.transcript, request.title),
        transcript=analysis["transcript"],
        summary_markdown=analysis["summary_markdown"],
        summary_json=serialize_json(analysis["summary"]),
        decisions_json="[]",
        risks_json="[]",
        follow_up_question=request.follow_up_question.strip(),
        follow_up_answer="",
    )
    db.add(meeting)
    db.flush()

    agent = run_action_agent(
        analysis["cleaned_transcript"],
        analysis["summary"],
    )

    if request.follow_up_question.strip():
        if request.summary_engine == "local":
            agent["answer"] = answer_follow_up_question(analysis["cleaned_transcript"], request.follow_up_question)
        else:
            agent["answer"] = str(analysis["summary"].get("follow_up_answer", "")).strip()

    meeting.decisions_json = serialize_json(agent.get("decisions", []))
    meeting.risks_json = serialize_json(agent.get("risks", []))
    meeting.follow_up_answer = str(agent.get("answer", "")).strip()

    for item in agent.get("action_items", []):
        db.add(
            ActionItem(
                meeting_id=meeting.id,
                task=str(item.get("task", "Unspecified task")),
                owner=str(item.get("owner", "Unassigned") or "Unassigned"),
                deadline=str(item.get("deadline", "Not mentioned") or "Not mentioned"),
                evidence=str(item.get("evidence", "") or ""),
                status="Open",
            )
        )

    db.commit()
    db.refresh(meeting)
    return get_meeting(db, meeting.id)


def list_meetings(db: Session, user_id: int | None = None) -> list[Meeting]:
    statement = (
        select(Meeting)
        .options(selectinload(Meeting.actions))
        .order_by(Meeting.created_at.desc(), Meeting.id.desc())
    )
    if user_id is not None:
        statement = statement.where(Meeting.user_id == user_id)
    result = db.scalars(statement)
    return list(result)


def get_meeting(db: Session, meeting_id: int, user_id: int | None = None) -> Meeting:
    statement = select(Meeting).options(selectinload(Meeting.actions)).where(Meeting.id == meeting_id)
    if user_id is not None:
        statement = statement.where(Meeting.user_id == user_id)
    meeting = db.scalar(statement)
    if meeting is None:
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
