import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import BinaryIO

from openai import OpenAI

from .config import load_environment


load_environment()


SUMMARY_SCHEMA = {
    "overview": "A short 2-4 sentence overview of the meeting.",
    "key_discussion_points": ["Specific points discussed."],
    "decisions_made": ["Decisions or 'None captured'."],
}

ACTION_ITEMS_SCHEMA = {
    "action_items": [
        {
            "task": "Concrete task to complete.",
            "owner": "Named owner or 'Unassigned'.",
            "deadline": "Deadline or 'Not mentioned'.",
            "evidence": "Short supporting quote or sentence from the transcript.",
        }
    ],
}

TRANSCRIPTION_SINGLE_FILE_LIMIT_BYTES = 25 * 1024 * 1024
TRANSCRIPTION_CHUNK_BYTES = 24 * 1024 * 1024
TRANSCRIPT_FORMAT_CHARS = 12000

MPEG_BITRATES = {
    ("1", "I"): [0, 32, 64, 96, 128, 160, 192, 224, 256, 288, 320, 352, 384, 416, 448, 0],
    ("1", "II"): [0, 32, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384, 0],
    ("1", "III"): [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0],
    ("2", "I"): [0, 32, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, 192, 224, 256, 0],
    ("2", "II"): [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0],
    ("2", "III"): [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0],
}

MPEG_SAMPLE_RATES = {
    "1": [44100, 48000, 32000, 0],
    "2": [22050, 24000, 16000, 0],
    "2.5": [11025, 12000, 8000, 0],
}


def normalize_summary_dict(summary: dict | str) -> dict:
    if isinstance(summary, str):
        try:
            summary = json.loads(summary)
        except json.JSONDecodeError:
            return {
                "overview": summary.strip() or "No overview returned.",
                "key_discussion_points": [],
                "decisions_made": [],
                "action_items": [],
            }

    return {
        "overview": summary.get("overview", "No overview returned."),
        "key_discussion_points": summary.get("key_discussion_points", []) or [],
        "decisions_made": summary.get("decisions_made", []) or [],
    }


def normalize_action_items_response(response: dict | str | list | None) -> list[dict[str, str]]:
    if isinstance(response, str):
        try:
            response = json.loads(response)
        except json.JSONDecodeError:
            return []

    if isinstance(response, list):
        raw_items = response
    elif isinstance(response, dict):
        raw_items = response.get("action_items", []) or response.get("actions", []) or response.get("items", [])
    else:
        raw_items = []

    action_items = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue

        task = str(item.get("task", "")).strip()
        if not task or task.lower() in {"none", "n/a", "not mentioned"}:
            continue

        action_items.append(
            {
                "task": task,
                "owner": str(item.get("owner", "Unassigned") or "Unassigned").strip() or "Unassigned",
                "deadline": str(item.get("deadline", "Not mentioned") or "Not mentioned").strip()
                or "Not mentioned",
                "evidence": str(item.get("evidence", "") or "").strip(),
            }
        )

    return action_items


def get_client() -> OpenAI:
    timeout_seconds = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "120"))
    return OpenAI(api_key=os.getenv("OPENAI_API_KEY"), timeout=timeout_seconds)


def _synchsafe_size(value: bytes) -> int:
    return (value[0] << 21) | (value[1] << 14) | (value[2] << 7) | value[3]


def _skip_id3v2_tag(data: bytes) -> int:
    if len(data) < 10 or data[:3] != b"ID3":
        return 0

    tag_size = 10 + _synchsafe_size(data[6:10])
    has_footer = bool(data[5] & 0x10)
    return tag_size + (10 if has_footer else 0)


def _mp3_frame_size(header: bytes) -> int | None:
    if len(header) < 4:
        return None

    header_value = int.from_bytes(header, "big")
    if (header_value & 0xFFE00000) != 0xFFE00000:
        return None

    version_bits = (header_value >> 19) & 0b11
    layer_bits = (header_value >> 17) & 0b11
    bitrate_index = (header_value >> 12) & 0b1111
    sample_rate_index = (header_value >> 10) & 0b11
    padding = (header_value >> 9) & 0b1

    version = {0b00: "2.5", 0b10: "2", 0b11: "1"}.get(version_bits)
    layer = {0b01: "III", 0b10: "II", 0b11: "I"}.get(layer_bits)
    if version is None or layer is None:
        return None

    bitrate_table_version = "1" if version == "1" else "2"
    bitrate_kbps = MPEG_BITRATES[(bitrate_table_version, layer)][bitrate_index]
    sample_rate = MPEG_SAMPLE_RATES[version][sample_rate_index]
    if bitrate_kbps == 0 or sample_rate == 0:
        return None

    bitrate = bitrate_kbps * 1000
    if layer == "I":
        return int(((12 * bitrate) / sample_rate + padding) * 4)
    if layer == "III" and version != "1":
        return int((72 * bitrate) / sample_rate + padding)
    return int((144 * bitrate) / sample_rate + padding)


def _split_mp3_frames(data: bytes, max_chunk_size: int = TRANSCRIPTION_CHUNK_BYTES) -> list[bytes]:
    chunks: list[bytes] = []
    current = bytearray()
    index = _skip_id3v2_tag(data)

    while index + 4 <= len(data):
        frame_size = _mp3_frame_size(data[index : index + 4])
        if frame_size is None or index + frame_size > len(data):
            index += 1
            continue

        frame = data[index : index + frame_size]
        if len(frame) > max_chunk_size:
            raise ValueError("One MP3 frame is too large to split safely.")

        if current and len(current) + len(frame) > max_chunk_size:
            chunks.append(bytes(current))
            current = bytearray()

        current.extend(frame)
        index += frame_size

    if current:
        chunks.append(bytes(current))

    if not chunks:
        raise ValueError(
            "This audio file is over 25 MB and could not be split safely. "
            "Please compress it below 25 MB or upload it as a standard MP3 file."
        )
    return chunks


def _write_temp_file(content: bytes, suffix: str) -> str:
    with NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
        temp_file.write(content)
        return temp_file.name


def _transcribe_file_path(client: OpenAI, model: str, file_path: str) -> str:
    with open(file_path, "rb") as audio_file:
        transcript = client.audio.transcriptions.create(
            model=model,
            file=audio_file,
            response_format="text",
        )
    return transcript if isinstance(transcript, str) else str(transcript)


def _split_text_for_formatting(text: str, max_chars: int = TRANSCRIPT_FORMAT_CHARS) -> list[str]:
    text = text.strip()
    if not text:
        return []

    paragraphs = []
    current = ""
    for sentence in text.replace("\r\n", "\n").replace("\r", "\n").split(". "):
        sentence = sentence.strip()
        if not sentence:
            continue
        if not sentence.endswith("."):
            sentence = f"{sentence}."

        if current and len(current) + len(sentence) + 1 > max_chars:
            paragraphs.append(current.strip())
            current = sentence
        else:
            current = f"{current} {sentence}".strip()

    if current:
        paragraphs.append(current.strip())
    return paragraphs


def format_transcript_text(raw_transcript: str, client: OpenAI | None = None) -> str:
    raw_transcript = raw_transcript.strip()
    if not raw_transcript:
        return ""

    client = client or get_client()
    model = os.getenv("OPENAI_SUMMARY_MODEL", "gpt-4o-mini")
    formatted_parts = []

    for part in _split_text_for_formatting(raw_transcript):
        prompt = f"""
Format this raw Whisper transcript into a clean transcript for a meeting app.

Rules:
- Preserve the original meaning, order, facts, names, dates, numbers, and action items.
- Add punctuation, capitalization, line breaks, and readable paragraphs.
- Format conversational sections with speaker labels so it reads like a meeting transcript.
- You may add plain generic labels such as "Speaker 1:" and "Speaker 2:" when the audio appears to switch turns.
- Do not invent real speaker names unless a name is clearly stated in the raw transcript.
- Do not invent timestamps, headings, facts, tasks, decisions, or other content.
- Do not use Markdown formatting. Never return bold labels like "**Speaker 1:**".
- Do not summarize, shorten, translate, or explain.
- Return only the formatted transcript text.

Raw transcript:
{part}
""".strip()

        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You format raw speech-to-text output into clean transcript text."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
        )
        formatted_parts.append((response.choices[0].message.content or "").strip())

    return "\n\n".join(part for part in formatted_parts if part)


def transcribe_audio(uploaded_file: BinaryIO, filename: str) -> str:
    model = os.getenv("OPENAI_TRANSCRIBE_MODEL", "whisper-1")
    suffix = Path(filename).suffix or ".mp3"
    audio_bytes = uploaded_file.read()

    if len(audio_bytes) <= TRANSCRIPTION_SINGLE_FILE_LIMIT_BYTES:
        client = get_client()
        temp_path = _write_temp_file(audio_bytes, suffix)
        try:
            raw_transcript = _transcribe_file_path(client, model, temp_path)
            return format_transcript_text(raw_transcript, client=client)
        finally:
            Path(temp_path).unlink(missing_ok=True)

    if suffix.lower() != ".mp3":
        raise ValueError(
            "This audio file is over 25 MB. Please compress it below 25 MB or upload it as an MP3 so it can be split."
        )

    client = get_client()
    temp_paths: list[str] = []
    try:
        transcripts = []
        for chunk in _split_mp3_frames(audio_bytes, max_chunk_size=TRANSCRIPTION_CHUNK_BYTES):
            temp_path = _write_temp_file(chunk, ".mp3")
            temp_paths.append(temp_path)
            raw_transcript = _transcribe_file_path(client, model, temp_path).strip()
            transcripts.append(format_transcript_text(raw_transcript, client=client))
        return "\n\n".join(transcript for transcript in transcripts if transcript)
    finally:
        for temp_path in temp_paths:
            Path(temp_path).unlink(missing_ok=True)


def summarize_transcript(cleaned_transcript: str, follow_up_question: str = "") -> dict:
    model = os.getenv("OPENAI_SUMMARY_MODEL", "gpt-4o-mini")
    schema = dict(SUMMARY_SCHEMA)
    follow_up_question = follow_up_question.strip()
    if follow_up_question:
        schema["follow_up_answer"] = "A direct answer to the follow-up question using only the transcript."

    prompt = f"""
Create a structured meeting summary from this cleaned transcript.

Return only valid JSON using this shape:
{json.dumps(schema, indent=2)}

Rules:
- Preserve important facts, decisions, numbers, names, deadlines, and risks.
- Do not invent decisions.
- If a follow-up question is provided, answer it directly and concisely using only the transcript.
- If the answer is not in the transcript, say "Not mentioned."

Follow-up question:
{follow_up_question or "None"}

Transcript:
{cleaned_transcript}
""".strip()

    response = get_client().chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "You are a careful meeting analyst who produces concise JSON summaries."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content or "{}"
    return json.loads(content)


def extract_action_items(cleaned_transcript: str) -> list[dict[str, str]]:
    model = os.getenv("OPENAI_SUMMARY_MODEL", "gpt-4o-mini")
    prompt = f"""
Extract concrete action items from this meeting transcript.

Return only valid JSON using this shape:
{json.dumps(ACTION_ITEMS_SCHEMA, indent=2)}

Rules:
- Include only real post-meeting tasks, deliverables, or follow-up work.
- Exclude commentary, explanations, opinions, agenda items, jokes, introductions, and filler.
- Exclude vague phrases such as "I'll tell you why", "I'll share one thing", "this should be helpful", or "we should think about it" unless they contain a concrete deliverable.
- Do not turn discussion topics into tasks.
- Do not invent tasks, owners, deadlines, or evidence.
- If an owner is not explicit, use "Unassigned".
- If a deadline is not explicit, use "Not mentioned".
- Evidence must be a short quote or sentence from the transcript that supports the task.
- If there are no concrete action items, return {{"action_items": []}}.

Transcript:
{cleaned_transcript}
""".strip()

    response = get_client().chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "You extract only concrete meeting action items as strict JSON."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.0,
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content or "{}"
    return normalize_action_items_response(content)


def answer_follow_up_question(cleaned_transcript: str, question: str) -> str:
    question = question.strip()
    if not question:
        return ""

    model = os.getenv("OPENAI_SUMMARY_MODEL", "gpt-4o-mini")
    prompt = f"""
Answer the follow-up question using only the meeting transcript.

Rules:
- Give the shortest useful answer.
- If the answer is a date, return only the date.
- Do not explain your reasoning.
- If the transcript does not contain the answer, say "Not mentioned."

Question:
{question}

Transcript:
{cleaned_transcript}
""".strip()

    response = get_client().chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "You answer meeting follow-up questions using only the transcript."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.0,
    )
    return (response.choices[0].message.content or "").strip()


def summary_to_markdown(summary: dict) -> str:
    summary = normalize_summary_dict(summary)
    lines = ["## Overview", summary.get("overview", "No overview returned."), ""]

    lines.append("## Key Discussion Points")
    for point in summary.get("key_discussion_points", []) or ["None captured"]:
        lines.append(f"- {point}")

    lines.extend(["", "## Decisions Made"])
    for decision in summary.get("decisions_made", []) or ["None captured"]:
        lines.append(f"- {decision}")

    return "\n".join(lines)
