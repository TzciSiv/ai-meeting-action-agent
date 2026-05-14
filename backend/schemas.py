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
    created_at: datetime


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserRead


class MeetingAnalyzeRequest(BaseModel):
    transcript: str = Field(..., min_length=1)
    follow_up_question: str = ""
    title: str | None = None
    summary_engine: Literal["gpt", "local"] = "gpt"


class MeetingUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=200)


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


class AnalyzeResponse(MeetingRead):
    pass
