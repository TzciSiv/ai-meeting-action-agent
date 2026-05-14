import json
from pathlib import Path

from .llm import normalize_summary_dict, summary_to_markdown
from .transcript_processing import process_transcript, split_transcript_into_chunks


DEFAULT_MODEL_DIR = Path("models/meeting-summarizer")
DEFAULT_BASE_MODEL = "t5-small"


def get_device():
    import torch

    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def load_summarization_model(model_dir: str | Path = DEFAULT_MODEL_DIR, base_model: str = DEFAULT_BASE_MODEL):
    try:
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
    except ImportError as exc:
        raise RuntimeError("Install the local-model dependencies first: pip install -r requirements.txt") from exc

    model_path = Path(model_dir)
    source = str(model_path) if model_path.exists() and any(model_path.iterdir()) else base_model
    tokenizer = AutoTokenizer.from_pretrained(source)
    model = AutoModelForSeq2SeqLM.from_pretrained(source)
    device = get_device()
    model.to(device)
    model.eval()
    return tokenizer, model, device, source


def generate_chunk_summary(
    chunk: str,
    tokenizer,
    model,
    device,
    max_input_tokens: int = 768,
    max_output_tokens: int = 180,
) -> str:
    import torch

    prompt = "summarize meeting: " + chunk
    inputs = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=max_input_tokens).to(device)
    with torch.no_grad():
        output_ids = model.generate(
            **inputs,
            max_new_tokens=max_output_tokens,
            num_beams=4,
            no_repeat_ngram_size=3,
            early_stopping=True,
        )
    return tokenizer.decode(output_ids[0], skip_special_tokens=True).strip()


def structure_generated_summary(raw_summary: str) -> dict:
    try:
        return normalize_summary_dict(json.loads(raw_summary))
    except json.JSONDecodeError:
        pass

    sections = {
        "overview": raw_summary.strip(),
        "key_discussion_points": [],
        "decisions_made": [],
        "action_items": [],
    }
    current_key = "overview"
    header_map = {
        "overview": "overview",
        "key points": "key_discussion_points",
        "key discussion points": "key_discussion_points",
        "decisions": "decisions_made",
        "decisions made": "decisions_made",
        "action items": "action_items",
    }

    for line in raw_summary.splitlines():
        stripped = line.strip().strip("#:")
        lowered = stripped.lower()
        if lowered in header_map:
            current_key = header_map[lowered]
            continue
        if not stripped:
            continue

        item = stripped.lstrip("-*0123456789. ").strip()
        if current_key == "overview":
            sections["overview"] = item
        elif current_key == "action_items":
            sections["action_items"].append({"task": item, "owner": "Unassigned", "deadline": "Not mentioned"})
        else:
            sections[current_key].append(item)

    return normalize_summary_dict(sections)


def summarize_with_loaded_model(
    transcript: str,
    tokenizer,
    model,
    device,
    source: str,
    chunk_words: int = 350,
) -> dict:
    cleaning = process_transcript(transcript)
    chunks = split_transcript_into_chunks(cleaning.cleaned_text, max_words=chunk_words)
    chunk_summaries = [
        generate_chunk_summary(chunk, tokenizer, model, device)
        for chunk in chunks
        if chunk.strip()
    ]
    combined = "\n".join(chunk_summaries)

    if len(chunk_summaries) > 1:
        combined = generate_chunk_summary(combined, tokenizer, model, device, max_input_tokens=768)

    summary = structure_generated_summary(combined)
    summary["model_source"] = source
    summary["chunk_count"] = len(chunks)
    return summary


def summarize_with_local_model(
    transcript: str,
    model_dir: str | Path = DEFAULT_MODEL_DIR,
    base_model: str = DEFAULT_BASE_MODEL,
    chunk_words: int = 350,
) -> dict:
    tokenizer, model, device, source = load_summarization_model(model_dir, base_model)
    return summarize_with_loaded_model(transcript, tokenizer, model, device, source, chunk_words)


def summarize_file(
    transcript_path: str | Path,
    model_dir: str | Path = DEFAULT_MODEL_DIR,
    base_model: str = DEFAULT_BASE_MODEL,
    reference_path: str | Path | None = None,
) -> dict:
    transcript = Path(transcript_path).read_text(encoding="utf-8")
    summary = summarize_with_local_model(transcript, model_dir=model_dir, base_model=base_model)
    markdown = summary_to_markdown(summary)
    return {"summary": summary, "summary_markdown": markdown}
