import io
import unittest
from types import SimpleNamespace

import backend.llm as llm_module
from backend.llm import _split_mp3_frames, format_transcript_text, transcribe_audio


def sample_mp3_frame() -> bytes:
    header = bytes.fromhex("fffb9000")
    return header + (b"\x00" * 413)


def sample_mp3(frame_count: int) -> bytes:
    return sample_mp3_frame() * frame_count


class RecordingTranscriptions:
    def __init__(self) -> None:
        self.upload_sizes: list[int] = []

    def create(self, model: str, file, response_format: str) -> str:
        content = file.read()
        self.upload_sizes.append(len(content))
        return f"transcript {len(self.upload_sizes)}"


class RecordingChatCompletions:
    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.temperatures: list[float | None] = []

    def create(self, model: str, messages: list[dict], **kwargs):
        self.prompts.append(messages[-1]["content"])
        self.temperatures.append(kwargs.get("temperature"))
        content = f"formatted transcript {len(self.prompts)}"
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


class RecordingAudio:
    def __init__(self) -> None:
        self.transcriptions = RecordingTranscriptions()


class RecordingChat:
    def __init__(self) -> None:
        self.completions = RecordingChatCompletions()


class RecordingClient:
    def __init__(self) -> None:
        self.audio = RecordingAudio()
        self.chat = RecordingChat()


class LlmTranscriptionTests(unittest.TestCase):
    def test_splits_mp3_on_frame_boundaries(self):
        chunks = _split_mp3_frames(sample_mp3(8), max_chunk_size=1000)

        self.assertEqual(len(chunks), 4)
        self.assertTrue(all(len(chunk) <= 1000 for chunk in chunks))
        self.assertTrue(all(chunk.startswith(bytes.fromhex("fffb9000")) for chunk in chunks))

    def test_transcribes_large_mp3_in_chunks(self):
        original_get_client = llm_module.get_client
        original_chunk_limit = llm_module.TRANSCRIPTION_CHUNK_BYTES
        client = RecordingClient()
        llm_module.get_client = lambda: client
        llm_module.TRANSCRIPTION_CHUNK_BYTES = 1000

        try:
            transcript = transcribe_audio(io.BytesIO(sample_mp3(8)), "meeting.mp3")
        finally:
            llm_module.TRANSCRIPTION_CHUNK_BYTES = original_chunk_limit
            llm_module.get_client = original_get_client

        self.assertEqual(
            transcript,
            "formatted transcript 1\n\nformatted transcript 2\n\nformatted transcript 3\n\nformatted transcript 4",
        )
        self.assertEqual(client.audio.transcriptions.upload_sizes, [834, 834, 834, 834])
        self.assertEqual(len(client.chat.completions.prompts), 4)

    def test_formats_raw_transcript_without_summarizing_instruction(self):
        client = RecordingClient()

        transcript = format_transcript_text("james will fix the android crash by tuesday", client=client)

        self.assertEqual(transcript, "formatted transcript 1")
        self.assertIn("Do not summarize", client.chat.completions.prompts[0])
        self.assertIn("generic labels", client.chat.completions.prompts[0])
        self.assertIn("Never return bold labels", client.chat.completions.prompts[0])
        self.assertIn("james will fix", client.chat.completions.prompts[0])
        self.assertIsNone(client.chat.completions.temperatures[0])

    def test_rejects_large_non_mp3_file(self):
        original_single_limit = llm_module.TRANSCRIPTION_SINGLE_FILE_LIMIT_BYTES
        llm_module.TRANSCRIPTION_SINGLE_FILE_LIMIT_BYTES = 10
        try:
            with self.assertRaisesRegex(ValueError, "too long for one transcription request"):
                transcribe_audio(io.BytesIO(b"not an mp3 file that is too large"), "meeting.wav")
        finally:
            llm_module.TRANSCRIPTION_SINGLE_FILE_LIMIT_BYTES = original_single_limit


if __name__ == "__main__":
    unittest.main()
