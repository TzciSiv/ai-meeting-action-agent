import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import BinaryIO

from openai import OpenAI

from .config import load_environment


load_environment()


TRANSCRIPTION_SINGLE_FILE_LIMIT_BYTES = 25 * 1024 * 1024
TRANSCRIPTION_CHUNK_BYTES = 6 * 1024 * 1024
TRANSCRIPT_FORMAT_CHARS = 12000
MP3_SUFFIXES = {".mp3", ".mpeg", ".mpga"}

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


def get_client() -> OpenAI:
    timeout_seconds = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "120"))
    return OpenAI(api_key=os.getenv("OPENAI_API_KEY"), timeout=timeout_seconds)


def supports_custom_temperature(model: str) -> bool:
    """GPT-5 chat models only support the default temperature value."""
    return not model.lower().startswith("gpt-5")


def create_chat_completion(
    client: OpenAI,
    model: str,
    messages: list[dict],
    temperature: float | None = None,
    **kwargs,
):
    request = {
        "model": model,
        "messages": messages,
        **kwargs,
    }
    if temperature is not None and supports_custom_temperature(model):
        request["temperature"] = temperature

    return client.chat.completions.create(**request)


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
            "This audio file could not be split safely. "
            "Please upload it as a standard MP3 file or use a shorter recording."
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
    model = os.getenv("OPENAI_SUMMARY_MODEL", "gpt-5-mini")
    formatted_parts = []

    for part in _split_text_for_formatting(raw_transcript):
        prompt = f"""
Format this raw speech-to-text transcript into a clean transcript for a meeting app.

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

        response = create_chat_completion(
            client,
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
    model = os.getenv("OPENAI_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe")
    suffix = Path(filename).suffix or ".mp3"
    is_mp3 = suffix.lower() in MP3_SUFFIXES
    audio_bytes = uploaded_file.read()
    client = get_client()

    if not is_mp3 and len(audio_bytes) > TRANSCRIPTION_SINGLE_FILE_LIMIT_BYTES:
        raise ValueError(
            "This audio is too long for one transcription request. "
            "Convert it to MP3 or use a shorter file."
        )

    chunks = (
        _split_mp3_frames(audio_bytes, max_chunk_size=TRANSCRIPTION_CHUNK_BYTES)
        if is_mp3 and len(audio_bytes) > TRANSCRIPTION_CHUNK_BYTES
        else [audio_bytes]
    )

    temp_paths: list[str] = []
    try:
        transcripts = []
        for chunk in chunks:
            temp_path = _write_temp_file(chunk, ".mp3" if is_mp3 else suffix)
            temp_paths.append(temp_path)
            raw_transcript = _transcribe_file_path(client, model, temp_path).strip()
            if raw_transcript:
                transcripts.append(format_transcript_text(raw_transcript, client=client))
        return "\n\n".join(transcript for transcript in transcripts if transcript)
    finally:
        for temp_path in temp_paths:
            Path(temp_path).unlink(missing_ok=True)
