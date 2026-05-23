import hashlib
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class PromptSpec:
    name: str
    version: str
    task_type: str
    purpose: str
    output_schema: str
    model_env_var: str
    default_model: str
    temperature: float
    safety_rules: tuple[str, ...]
    system_message: str
    template: str

    def render(self, **values: str) -> str:
        return self.template.format(**values).strip()

    @property
    def prompt_id(self) -> str:
        return self.name

    @property
    def template_hash(self) -> str:
        payload = f"{self.system_message}\n{self.template}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def model_name(self) -> str:
        return os.getenv(self.model_env_var, self.default_model)


SUMMARY_PROMPT = PromptSpec(
    name="meeting_summary",
    version="2026-05-ops-v1",
    task_type="summary",
    purpose="Create a concise structured summary with grounded decisions.",
    output_schema="SummaryOutput",
    model_env_var="OPENAI_SUMMARY_MODEL",
    default_model="gpt-5-mini",
    temperature=0.2,
    safety_rules=(
        "Preserve important facts, decisions, names, dates, numbers, deadlines, and risks.",
        "Do not invent decisions.",
        "Keep the overview concise.",
    ),
    system_message="You are a careful meeting analyst who produces concise structured summaries.",
    template="""
Create a structured meeting summary from this cleaned transcript.

Rules:
- Preserve important facts, decisions, numbers, names, deadlines, and risks.
- Do not invent decisions.
- Keep the overview concise.

Transcript:
{cleaned_transcript}
""",
)


INSIGHTS_PROMPT = PromptSpec(
    name="meeting_insights",
    version="2026-05-ops-v1",
    task_type="action_and_risk_extraction",
    purpose="Extract grounded action items and risks from a meeting transcript.",
    output_schema="MeetingInsightsOutput",
    model_env_var="OPENAI_SUMMARY_MODEL",
    default_model="gpt-5-mini",
    temperature=0.0,
    safety_rules=(
        "Include only real post-meeting tasks, deliverables, or follow-up work.",
        "Do not invent tasks, owners, deadlines, evidence, or risks.",
        "Evidence must be a short quote or sentence from the transcript.",
        "Do not turn vague discussion topics into action items.",
    ),
    system_message="You extract concrete meeting actions and grounded risks as structured data.",
    template="""
Extract concrete action items and meeting risks from this transcript.

Action item rules:
- Include only real post-meeting tasks, deliverables, or follow-up work.
- Exclude commentary, explanations, opinions, agenda items, jokes, introductions, and filler.
- Exclude vague phrases unless they contain a concrete deliverable.
- Do not turn discussion topics into tasks.
- Do not invent tasks, owners, deadlines, or evidence.
- If an owner is not explicit, use "Unassigned".
- If a deadline is not explicit, use "Not mentioned".
- Evidence must be a short quote or sentence from the transcript that supports the task.

Risk rules:
- Include only risks, blockers, concerns, errors, customer issues, security/privacy concerns, deadlines, or reliability problems that appear in the transcript.
- Do not invent risks.

Transcript:
{cleaned_transcript}
""",
)


FOLLOW_UP_PROMPT = PromptSpec(
    name="grounded_follow_up",
    version="2026-05-ops-v2",
    task_type="rag_qa",
    purpose="Answer a user question using only retrieved transcript evidence.",
    output_schema="FollowUpAnswerOutput",
    model_env_var="OPENAI_SUMMARY_MODEL",
    default_model="gpt-5-mini",
    temperature=0.0,
    safety_rules=(
        "Use only retrieved transcript sources.",
        'If the sources do not contain the answer, return "Not mentioned".',
        "Do not explain hidden reasoning.",
        "Do not use outside knowledge.",
    ),
    system_message="You answer meeting follow-up questions using only retrieved transcript evidence.",
    template="""
Answer the follow-up question using only the retrieved transcript sources.

Rules:
- Give the shortest useful answer.
- If the answer is a date, return only the date.
- Do not explain your reasoning.
- If the sources do not contain the answer, return "Not mentioned".

Question:
{question}

Retrieved transcript sources:
{source_text}
""",
)


PROMPT_REGISTRY = {
    SUMMARY_PROMPT.name: SUMMARY_PROMPT,
    INSIGHTS_PROMPT.name: INSIGHTS_PROMPT,
    FOLLOW_UP_PROMPT.name: FOLLOW_UP_PROMPT,
}


def get_prompt_specs() -> dict[str, PromptSpec]:
    return dict(PROMPT_REGISTRY)


def prompt_inventory() -> list[dict[str, object]]:
    return [
        {
            "name": prompt.name,
            "prompt_id": prompt.prompt_id,
            "version": prompt.version,
            "task_type": prompt.task_type,
            "purpose": prompt.purpose,
            "output_schema": prompt.output_schema,
            "model": prompt.model_name(),
            "temperature": prompt.temperature,
            "template_hash": prompt.template_hash,
            "safety_rules": list(prompt.safety_rules),
        }
        for prompt in PROMPT_REGISTRY.values()
    ]


def build_summary_messages(cleaned_transcript: str) -> list[tuple[str, str]]:
    return [
        ("system", SUMMARY_PROMPT.system_message),
        ("human", SUMMARY_PROMPT.render(cleaned_transcript=cleaned_transcript)),
    ]


def build_insights_messages(cleaned_transcript: str) -> list[tuple[str, str]]:
    return [
        ("system", INSIGHTS_PROMPT.system_message),
        ("human", INSIGHTS_PROMPT.render(cleaned_transcript=cleaned_transcript)),
    ]


def build_follow_up_messages(question: str, source_text: str) -> list[tuple[str, str]]:
    return [
        ("system", FOLLOW_UP_PROMPT.system_message),
        ("human", FOLLOW_UP_PROMPT.render(question=question, source_text=source_text)),
    ]
