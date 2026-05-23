import os
import re
import time
from typing import Any, Type, TypedDict

from pydantic import BaseModel, Field

from .config import load_environment
from .governance import NOT_MENTIONED_RESPONSE, is_not_mentioned_answer, make_ai_run_trace
from .observability import increment_counter, timed_operation
from .prompts import (
    FOLLOW_UP_PROMPT,
    INSIGHTS_PROMPT,
    SUMMARY_PROMPT,
    build_follow_up_messages,
    build_insights_messages,
    build_summary_messages,
)


CHUNK_SIZE = 1200
CHUNK_OVERLAP = 200
RETRIEVAL_LIMIT = 5
DEFAULT_VECTOR_COLLECTION = "meeting_transcript_chunks"
ANONYMOUS_USER_KEY = "__anonymous__"


class ActionItemOutput(BaseModel):
    task: str = Field(description="Concrete post-meeting task to complete.")
    owner: str = Field(description="Named owner, or Unassigned.")
    deadline: str = Field(description="Deadline, or Not mentioned.")
    evidence: str = Field(description="Short transcript quote or sentence supporting the task.")


class SummaryOutput(BaseModel):
    overview: str = Field(description="A short 2-4 sentence meeting overview.")
    key_discussion_points: list[str] = Field(description="Specific points discussed.")
    decisions_made: list[str] = Field(description="Decisions that were made.")


class MeetingInsightsOutput(BaseModel):
    action_items: list[ActionItemOutput] = Field(description="Concrete post-meeting tasks.")
    risks: list[str] = Field(description="Risks, blockers, or important concerns.")


class FollowUpAnswerOutput(BaseModel):
    answer: str = Field(description=f'Grounded answer, or "{NOT_MENTIONED_RESPONSE}".')


class MeetingAnalysisResult(BaseModel):
    transcript: str
    cleaned_transcript: str
    summary: dict[str, Any]
    summary_markdown: str
    action_items: list[dict[str, str]]
    decisions: list[str]
    risks: list[str]
    follow_up_question: str = ""
    follow_up_answer: str = ""
    follow_up_sources: list[dict[str, Any]] = Field(default_factory=list)
    ai_run_traces: list[dict[str, Any]] = Field(default_factory=list)


class MeetingAnalysisState(TypedDict, total=False):
    transcript: str
    cleaned_transcript: str
    meeting_id: int
    user_id: int | None
    follow_up_question: str
    summary: dict[str, Any]
    summary_markdown: str
    action_items: list[dict[str, str]]
    decisions: list[str]
    risks: list[str]
    chunks: list[str]
    stored_chunk_ids: list[str]
    follow_up_sources: list[dict[str, Any]]
    follow_up_answer: str
    ai_run_traces: list[dict[str, Any]]
    prompt_version_ids: dict[str, int]


def supports_custom_temperature(model: str) -> bool:
    """GPT-5 chat models only support the default temperature value."""
    return not model.lower().startswith("gpt-5")


def _clean_string_list(values: Any) -> list[str]:
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        return []
    return [str(value).strip() for value in values if str(value).strip()]


def normalize_summary_output(summary: SummaryOutput | dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(summary, BaseModel):
        summary_data = summary.model_dump()
    elif isinstance(summary, dict):
        summary_data = summary
    else:
        summary_data = {}

    overview = str(summary_data.get("overview") or "No overview returned.").strip()
    return {
        "overview": overview or "No overview returned.",
        "key_discussion_points": _clean_string_list(summary_data.get("key_discussion_points", [])),
        "decisions_made": _clean_string_list(summary_data.get("decisions_made", [])),
    }


def normalize_action_items(items: Any) -> list[dict[str, str]]:
    if isinstance(items, BaseModel):
        items = [items]
    if not isinstance(items, list):
        return []

    action_items: list[dict[str, str]] = []
    for item in items:
        if isinstance(item, BaseModel):
            item_data = item.model_dump()
        elif isinstance(item, dict):
            item_data = item
        else:
            continue

        task = str(item_data.get("task", "")).strip()
        if not task or task.lower() in {"none", "n/a", "not mentioned"}:
            continue

        action_items.append(
            {
                "task": task,
                "owner": str(item_data.get("owner") or "Unassigned").strip() or "Unassigned",
                "deadline": str(item_data.get("deadline") or "Not mentioned").strip() or "Not mentioned",
                "evidence": str(item_data.get("evidence") or "").strip(),
            }
        )
    return action_items


def summary_to_markdown(summary: dict[str, Any]) -> str:
    normalized = normalize_summary_output(summary)
    lines = ["## Overview", normalized["overview"], ""]

    lines.append("## Key Discussion Points")
    for point in normalized["key_discussion_points"] or ["None captured"]:
        lines.append(f"- {point}")

    return "\n".join(lines)


def build_chat_model(temperature: float | None = None):
    load_environment()
    from langchain_openai import ChatOpenAI

    model = os.getenv("OPENAI_SUMMARY_MODEL", "gpt-5-mini")
    timeout_seconds = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "120"))
    kwargs: dict[str, Any] = {
        "model": model,
        "timeout": timeout_seconds,
    }
    if temperature is not None and supports_custom_temperature(model):
        kwargs["temperature"] = temperature
    return ChatOpenAI(**kwargs)


def summary_model_name() -> str:
    return os.getenv("OPENAI_SUMMARY_MODEL", "gpt-5-mini")


def embedding_model_name() -> str:
    return os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")


def invoke_structured_model(schema: Type[BaseModel], messages: list[tuple[str, str]], temperature: float | None = None):
    return build_chat_model(temperature=temperature).with_structured_output(schema).invoke(messages)


def prompt_version_id(state: MeetingAnalysisState, prompt_name: str) -> int | None:
    value = state.get("prompt_version_ids", {}).get(prompt_name)
    return int(value) if value is not None else None


def append_trace(state: MeetingAnalysisState, trace: dict[str, Any]) -> list[dict[str, Any]]:
    return [*state.get("ai_run_traces", []), trace]


def build_embedding_model():
    load_environment()
    from langchain_openai import OpenAIEmbeddings

    return OpenAIEmbeddings(
        model=os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"),
        timeout=float(os.getenv("OPENAI_TIMEOUT_SECONDS", "120")),
    )


def build_vector_store():
    load_environment()
    from langchain_postgres import PGVector

    connection = os.getenv("DATABASE_URL")
    if not connection:
        raise RuntimeError("DATABASE_URL is required for LangChain PGVector retrieval.")

    return PGVector(
        embeddings=build_embedding_model(),
        collection_name=os.getenv("LANGCHAIN_PGVECTOR_COLLECTION", DEFAULT_VECTOR_COLLECTION),
        connection=connection,
        use_jsonb=True,
    )


def build_text_splitter():
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    return RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        length_function=len,
        is_separator_regex=False,
    )


def make_document(page_content: str, metadata: dict[str, Any]):
    from langchain_core.documents import Document

    return Document(page_content=page_content, metadata=metadata)


def metadata_user_id(user_id: int | None) -> int | str:
    return user_id if user_id is not None else ANONYMOUS_USER_KEY


def chunk_document_id(meeting_id: int, user_id: int | None, chunk_index: int) -> str:
    return f"meeting:{meeting_id}:user:{metadata_user_id(user_id)}:chunk:{chunk_index}"


def normalize_transcript_text(text: str) -> str:
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\s+([,.;:!?])", r"\1", cleaned)
    cleaned = re.sub(r"([,.;:!?])(?=\S)", r"\1 ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def clean_transcript_node(state: MeetingAnalysisState) -> dict[str, str]:
    with timed_operation("transcript.clean"):
        transcript = state.get("transcript", "")
        return {"cleaned_transcript": normalize_transcript_text(transcript)}


def summarize_node(state: MeetingAnalysisState) -> dict[str, Any]:
    with timed_operation(
        "llm.summarize",
        model=summary_model_name(),
        prompt_name=SUMMARY_PROMPT.name,
        prompt_version=SUMMARY_PROMPT.version,
    ):
        messages = build_summary_messages(state.get("cleaned_transcript", ""))
        started = time.perf_counter()
        output = invoke_structured_model(
            SummaryOutput,
            messages,
            temperature=SUMMARY_PROMPT.temperature,
        )
        summary = normalize_summary_output(output)
        return {
            "summary": summary,
            "summary_markdown": summary_to_markdown(summary),
            "decisions": summary["decisions_made"],
            "ai_run_traces": append_trace(
                state,
                make_ai_run_trace(
                    SUMMARY_PROMPT,
                    prompt_version_id(state, SUMMARY_PROMPT.name),
                    summary_model_name(),
                    messages,
                    output,
                    started,
                ),
            ),
        }


def extract_insights_node(state: MeetingAnalysisState) -> dict[str, Any]:
    with timed_operation(
        "llm.extract_insights",
        model=summary_model_name(),
        prompt_name=INSIGHTS_PROMPT.name,
        prompt_version=INSIGHTS_PROMPT.version,
    ):
        messages = build_insights_messages(state.get("cleaned_transcript", ""))
        started = time.perf_counter()
        output = invoke_structured_model(
            MeetingInsightsOutput,
            messages,
            temperature=INSIGHTS_PROMPT.temperature,
        )
        output_data = output.model_dump() if isinstance(output, BaseModel) else dict(output or {})
        return {
            "action_items": normalize_action_items(output_data.get("action_items", [])),
            "risks": _clean_string_list(output_data.get("risks", [])),
            "ai_run_traces": append_trace(
                state,
                make_ai_run_trace(
                    INSIGHTS_PROMPT,
                    prompt_version_id(state, INSIGHTS_PROMPT.name),
                    summary_model_name(),
                    messages,
                    output,
                    started,
                ),
            ),
        }


def split_transcript_node(state: MeetingAnalysisState) -> dict[str, list[str]]:
    with timed_operation("rag.split_transcript"):
        cleaned_transcript = state.get("cleaned_transcript", "")
        chunks = [chunk.strip() for chunk in build_text_splitter().split_text(cleaned_transcript) if chunk.strip()]
        increment_counter("rag.chunks.created", len(chunks))
        return {"chunks": chunks}


def store_chunks_node(state: MeetingAnalysisState) -> dict[str, list[str]]:
    with timed_operation("rag.store_chunks", embedding_model=embedding_model_name()):
        chunks = state.get("chunks", [])
        meeting_id = int(state.get("meeting_id", 0))
        user_id = state.get("user_id")
        if not chunks or not meeting_id:
            return {"stored_chunk_ids": []}

        documents = []
        document_ids = []
        user_key = metadata_user_id(user_id)
        for chunk_index, content in enumerate(chunks):
            metadata = {
                "meeting_id": meeting_id,
                "user_id": user_key,
                "chunk_index": chunk_index,
            }
            documents.append(make_document(content, metadata))
            document_ids.append(chunk_document_id(meeting_id, user_id, chunk_index))

        build_vector_store().add_documents(documents, ids=document_ids)
        increment_counter("rag.chunks.stored", len(document_ids))
        return {"stored_chunk_ids": document_ids}


def retrieve_sources_node(state: MeetingAnalysisState) -> dict[str, list[dict[str, Any]]]:
    with timed_operation("rag.retrieve_sources", embedding_model=embedding_model_name()):
        question = state.get("follow_up_question", "").strip()
        meeting_id = int(state.get("meeting_id", 0))
        if not question or not meeting_id:
            return {"follow_up_sources": []}

        vector_store = build_vector_store()
        filters = {
            "meeting_id": meeting_id,
            "user_id": metadata_user_id(state.get("user_id")),
        }

        if hasattr(vector_store, "similarity_search_with_relevance_scores"):
            results = vector_store.similarity_search_with_relevance_scores(question, k=RETRIEVAL_LIMIT, filter=filters)
        else:
            results = vector_store.similarity_search_with_score(question, k=RETRIEVAL_LIMIT, filter=filters)

        sources: list[dict[str, Any]] = []
        for rank, (document, score) in enumerate(results, start=1):
            metadata = getattr(document, "metadata", {}) or {}
            sources.append(
                {
                    "chunk_index": int(metadata.get("chunk_index", rank - 1)),
                    "content": str(getattr(document, "page_content", "")),
                    "rank": rank,
                    "score": float(score or 0.0),
                }
            )
        if sources:
            increment_counter("rag.sources.retrieved", len(sources))
        else:
            increment_counter("rag.sources.empty")
        return {"follow_up_sources": sources}


def normalize_follow_up_answer(output: FollowUpAnswerOutput | dict[str, Any] | None) -> str:
    if isinstance(output, BaseModel):
        output_data = output.model_dump()
    elif isinstance(output, dict):
        output_data = output
    else:
        output_data = {}

    answer = str(output_data.get("answer") or "").strip()
    if not answer or is_not_mentioned_answer(answer):
        return NOT_MENTIONED_RESPONSE
    return answer


def answer_follow_up_node(state: MeetingAnalysisState) -> dict[str, Any]:
    with timed_operation(
        "llm.answer_follow_up",
        model=summary_model_name(),
        prompt_name=FOLLOW_UP_PROMPT.name,
        prompt_version=FOLLOW_UP_PROMPT.version,
    ):
        question = state.get("follow_up_question", "").strip()
        if not question:
            return {"follow_up_answer": ""}

        sources = state.get("follow_up_sources", [])
        if not sources:
            increment_counter("rag.follow_up.not_mentioned")
            return {"follow_up_answer": NOT_MENTIONED_RESPONSE, "follow_up_sources": []}

        source_text = "\n\n".join(
            f"Source {source.get('rank', index)}:\n{source.get('content', '').strip()}"
            for index, source in enumerate(sources, start=1)
            if source.get("content", "").strip()
        )
        if not source_text:
            return {"follow_up_answer": NOT_MENTIONED_RESPONSE, "follow_up_sources": []}

        messages = build_follow_up_messages(question, source_text)
        started = time.perf_counter()
        output = invoke_structured_model(
            FollowUpAnswerOutput,
            messages,
            temperature=FOLLOW_UP_PROMPT.temperature,
        )
        answer = normalize_follow_up_answer(output)
        answer_is_not_mentioned = is_not_mentioned_answer(answer)
        if answer_is_not_mentioned:
            increment_counter("rag.follow_up.not_mentioned")
        return {
            "follow_up_answer": answer,
            "follow_up_sources": [] if answer_is_not_mentioned else sources,
            "ai_run_traces": append_trace(
                state,
                make_ai_run_trace(
                    FOLLOW_UP_PROMPT,
                    prompt_version_id(state, FOLLOW_UP_PROMPT.name),
                    summary_model_name(),
                    messages,
                    output,
                    started,
                    retrieved_chunk_ids=[
                        f"meeting:{state.get('meeting_id', 0)}:chunk:{source.get('chunk_index')}"
                        for source in sources
                    ],
                ),
            ),
        }


def compile_analysis_graph():
    from langgraph.graph import END, START, StateGraph

    graph = StateGraph(MeetingAnalysisState)
    graph.add_node("clean_transcript", clean_transcript_node)
    graph.add_node("summarize", summarize_node)
    graph.add_node("extract_insights", extract_insights_node)
    graph.add_node("split_transcript", split_transcript_node)
    graph.add_node("store_chunks", store_chunks_node)
    graph.add_node("retrieve_sources", retrieve_sources_node)
    graph.add_node("answer_follow_up", answer_follow_up_node)

    graph.add_edge(START, "clean_transcript")
    graph.add_edge("clean_transcript", "summarize")
    graph.add_edge("summarize", "extract_insights")
    graph.add_edge("extract_insights", "split_transcript")
    graph.add_edge("split_transcript", "store_chunks")
    graph.add_edge("store_chunks", "retrieve_sources")
    graph.add_edge("retrieve_sources", "answer_follow_up")
    graph.add_edge("answer_follow_up", END)
    return graph.compile()


def result_from_state(state: MeetingAnalysisState) -> MeetingAnalysisResult:
    summary = normalize_summary_output(state.get("summary", {}))
    follow_up_answer = str(state.get("follow_up_answer", "") or "").strip()
    return MeetingAnalysisResult(
        transcript=state.get("transcript", ""),
        cleaned_transcript=state.get("cleaned_transcript", ""),
        summary=summary,
        summary_markdown=state.get("summary_markdown") or summary_to_markdown(summary),
        action_items=normalize_action_items(state.get("action_items", [])),
        decisions=_clean_string_list(state.get("decisions", summary.get("decisions_made", []))),
        risks=_clean_string_list(state.get("risks", [])),
        follow_up_question=state.get("follow_up_question", ""),
        follow_up_answer=follow_up_answer,
        follow_up_sources=[] if is_not_mentioned_answer(follow_up_answer) else list(state.get("follow_up_sources", [])),
        ai_run_traces=list(state.get("ai_run_traces", [])),
    )


def run_meeting_analysis_graph(
    transcript: str,
    follow_up_question: str = "",
    meeting_id: int = 0,
    user_id: int | None = None,
    prompt_version_ids: dict[str, int] | None = None,
) -> dict[str, Any]:
    increment_counter("graph.runs")
    try:
        with timed_operation("analysis.graph.run", success_counter="graph.success", failure_counter="graph.failure"):
            graph = compile_analysis_graph()
            state = graph.invoke(
                {
                    "transcript": transcript,
                    "follow_up_question": follow_up_question.strip(),
                    "meeting_id": meeting_id,
                    "user_id": user_id,
                    "prompt_version_ids": prompt_version_ids or {},
                    "ai_run_traces": [],
                }
            )
            return result_from_state(state).model_dump()
    except Exception:
        raise
