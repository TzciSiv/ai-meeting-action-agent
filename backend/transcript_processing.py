import re
from dataclasses import dataclass


FILLER_WORDS = {
    "ah",
    "er",
    "erm",
    "hmm",
    "like",
    "mm",
    "uh",
    "uhh",
    "um",
    "umm",
    "you know",
}

SPEAKER_PATTERN = re.compile(
    r"(?im)^\s*(?P<speaker>(?:speaker\s*\d+|participant\s*\d+|[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,2}))\s*[:\-]\s+"
)


@dataclass
class TranscriptProcessingResult:
    raw_text: str
    cleaned_text: str
    filler_words_removed: int
    detected_speakers: list[str]
    chunks: list[str]


def normalize_spacing_and_punctuation(text: str) -> str:
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\s+([,.;:!?])", r"\1", cleaned)
    cleaned = re.sub(r"([,.;:!?])(?=\S)", r"\1 ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def remove_filler_words(text: str) -> tuple[str, int]:
    phrases = sorted(FILLER_WORDS, key=len, reverse=True)
    pattern = re.compile(r"\b(" + "|".join(re.escape(word) for word in phrases) + r")\b[, ]*", re.IGNORECASE)
    matches = pattern.findall(text)
    cleaned = pattern.sub("", text)
    return cleaned, len(matches)


def detect_speakers(text: str) -> list[str]:
    speakers = []
    seen = set()
    for match in SPEAKER_PATTERN.finditer(text):
        speaker = re.sub(r"\s+", " ", match.group("speaker")).strip()
        key = speaker.lower()
        if key not in seen:
            seen.add(key)
            speakers.append(speaker)
    return speakers


def split_sentences(text: str) -> list[str]:
    return re.findall(r"[^.!?\n]+[.!?]?", text)


def split_transcript_into_chunks(text: str, max_words: int = 350, overlap_words: int = 40) -> list[str]:
    sentences = [sentence.strip() for sentence in split_sentences(text) if sentence.strip()]
    if not sentences:
        words = text.split()
        return [" ".join(words[index : index + max_words]) for index in range(0, len(words), max_words)]

    chunks = []
    current_words: list[str] = []

    for sentence in sentences:
        sentence_words = sentence.split()
        if current_words and len(current_words) + len(sentence_words) > max_words:
            chunks.append(" ".join(current_words))
            current_words = current_words[-overlap_words:] if overlap_words > 0 else []
        current_words.extend(sentence_words)

    if current_words:
        chunks.append(" ".join(current_words))

    return chunks


def process_transcript(text: str) -> TranscriptProcessingResult:
    normalized = normalize_spacing_and_punctuation(text)
    no_fillers, removed_count = remove_filler_words(normalized)
    cleaned = normalize_spacing_and_punctuation(no_fillers)
    return TranscriptProcessingResult(
        raw_text=text,
        cleaned_text=cleaned,
        filler_words_removed=removed_count,
        detected_speakers=detect_speakers(cleaned),
        chunks=split_transcript_into_chunks(cleaned),
    )
