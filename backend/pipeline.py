from dataclasses import dataclass

from .action_agent import run_action_agent
from .llm import summarize_transcript, summary_to_markdown, transcribe_audio
from .transcript_processing import TranscriptProcessingResult, process_transcript


@dataclass
class PipelineResult:
    transcript: str
    cleaning: TranscriptProcessingResult
    summary: dict
    summary_markdown: str
    agent: dict
    summary_engine: str


def run_from_audio(uploaded_file, filename: str, summary_engine: str = "local", question: str = "") -> PipelineResult:
    transcript = transcribe_audio(uploaded_file, filename)
    return run_from_transcript(transcript, summary_engine=summary_engine, question=question)


def run_from_transcript(
    transcript: str,
    summary_engine: str = "local",
    model_dir: str = "models/meeting-summarizer",
    base_model: str = "t5-small",
    reference_summary: str | None = None,
    question: str = "",
) -> PipelineResult:
    cleaning = process_transcript(transcript)

    if summary_engine == "gpt":
        summary = summarize_transcript(cleaning.cleaned_text)
    else:
        from .local_model import summarize_with_local_model

        summary = summarize_with_local_model(cleaning.cleaned_text, model_dir=model_dir, base_model=base_model)

    markdown = summary_to_markdown(summary)
    agent = run_action_agent(cleaning.cleaned_text, summary)
    return PipelineResult(
        transcript=transcript,
        cleaning=cleaning,
        summary=summary,
        summary_markdown=markdown,
        agent=agent,
        summary_engine=summary_engine,
    )
