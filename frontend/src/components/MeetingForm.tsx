import { FormEvent, useState } from "react";
import { analyzeMeeting, transcribeMeetingAudio } from "../api";
import type { AnalyzeRequest, Meeting, TranscriptionJob } from "../types";

interface Props {
  transcript: string;
  onTranscriptChange: (transcript: string) => void;
  onAnalyze: (meeting: Meeting) => Promise<void>;
  onShowTranscriptionJob: () => void;
  onTranscriptionJobChange: (job: TranscriptionJob) => void;
}

export default function MeetingForm({
  transcript,
  onTranscriptChange,
  onAnalyze,
  onShowTranscriptionJob,
  onTranscriptionJobChange,
}: Props) {
  const [title, setTitle] = useState("");
  const [question, setQuestion] = useState("When was the day of meeting?");
  const [engine, setEngine] = useState<AnalyzeRequest["summary_engine"]>("gpt");
  const [audioFile, setAudioFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");

    window.setTimeout(() => {
      document.getElementById("run-status")?.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 0);

    try {
      const meeting = await analyzeMeeting({
        title: title || undefined,
        transcript,
        follow_up_question: question,
        summary_engine: engine,
      });
      await onAnalyze(meeting);
      window.setTimeout(() => {
        document.getElementById("agent-results")?.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 100);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not analyze meeting.");
    } finally {
      setLoading(false);
    }
  }

  async function handleTranscribe() {
    if (!audioFile) return;
    const job: TranscriptionJob = {
      fileName: audioFile.name,
      fileSize: audioFile.size,
      status: "running",
      startedAt: new Date().toISOString(),
    };
    setTranscribing(true);
    setError("");
    onTranscriptionJobChange(job);
    onShowTranscriptionJob();
    try {
      const result = await transcribeMeetingAudio(audioFile);
      onTranscriptChange(result.transcript);
      onTranscriptionJobChange({
        ...job,
        status: "completed",
        completedAt: new Date().toISOString(),
        transcriptLength: result.transcript.length,
      });
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "Could not transcribe audio.";
      setError(message);
      onTranscriptionJobChange({
        ...job,
        status: "failed",
        completedAt: new Date().toISOString(),
        error: message,
      });
    } finally {
      setTranscribing(false);
    }
  }

  return (
    <section className="panel analyze-panel">
      <form className="meeting-form" onSubmit={handleSubmit}>
        <div className="section-heading">
          <div>
            <p className="eyebrow">Analyze a meeting</p>
            <h2>Meeting Input</h2>
          </div>
        </div>

        <div className="form-row">
          <label>
            Meeting title
            <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Weekly product sync" />
          </label>
          <label>
            Summary model
            <select value={engine} onChange={(event) => setEngine(event.target.value as AnalyzeRequest["summary_engine"])}>
              <option value="gpt">GPT model</option>
              <option value="local">My trained model</option>
            </select>
          </label>
        </div>

        <div className="audio-row">
          <label>
            Upload meeting audio
            <input
              type="file"
              accept="audio/*,.mp3,.mp4,.mpeg,.mpga,.m4a,.wav,.webm"
              onChange={(event) => setAudioFile(event.target.files?.[0] ?? null)}
            />
          </label>
          <button
            className={`button ${audioFile ? "primary" : "secondary"}`}
            type="button"
            disabled={!audioFile || transcribing}
            onClick={handleTranscribe}
          >
            {transcribing ? "Transcribing..." : "Transcribe audio"}
          </button>
        </div>

        <label>
          Whisper API transcript output
          <textarea value={transcript} onChange={(event) => onTranscriptChange(event.target.value)} rows={12} />
        </label>

        <label>
          Ask a follow-up question
          <input value={question} onChange={(event) => setQuestion(event.target.value)} />
        </label>

        {error && <p className="error">{error}</p>}
        {loading && (
          <div className="run-status" id="run-status">
            <strong>Agent is running</strong>
            <span>Reading meeting, creating summary, finding actions, and saving everything to SQLite.</span>
          </div>
        )}
        <button className="button primary" disabled={loading || !transcript.trim()}>
          {loading ? "Running agent..." : "Run AI Meeting Agent"}
        </button>
      </form>
    </section>
  );
}
