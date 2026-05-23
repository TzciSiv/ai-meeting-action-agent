import { FormEvent, useState } from "react";
import type { DragEvent } from "react";
import { importTranscriptDocument } from "../api";
import type { ActiveAnalysisJob } from "../types";

interface Props {
  transcript: string;
  onTranscriptChange: (transcript: string) => void;
  analysisJob: ActiveAnalysisJob | null;
  authenticated: boolean;
  onRequestSignIn: () => void;
  onAnalyzeMeeting: (form: FormData) => Promise<void>;
  onTranscribeAudio: (file: File) => Promise<void>;
}

function isDocxFile(file: File) {
  return file.name.toLowerCase().endsWith(".docx");
}

function hasDraggedFiles(dataTransfer: DataTransfer) {
  return (
    Array.from(dataTransfer.types).includes("Files") ||
    Array.from(dataTransfer.items).some((item) => item.kind === "file")
  );
}

function firstFile(files: FileList | null) {
  return files && files.length > 0 ? files[0] : null;
}

function pipelineStepLabel(job: Pick<ActiveAnalysisJob, "currentStep"> | null, fallback = "Queued") {
  const step = job?.currentStep ?? fallback;
  const labels: Record<string, string> = {
    ingestion_event: "Upload recorded",
    transcription_queued: "Transcription queued",
    transcribing: "Transcribing audio",
    extracting_transcript: "Extracting transcript",
    transcript_stored: "Transcript stored",
    analysis_job_queued: "Analysis job queued",
    analysis_running: "Running governed analysis",
    embeddings_created: "Embeddings created",
    analysis_completed: "Analysis completed",
    analysis_failed: "Analysis failed",
  };
  return labels[step] ?? step.replace(/_/g, " ");
}

export default function MeetingForm({
  transcript,
  onTranscriptChange,
  analysisJob,
  authenticated,
  onRequestSignIn,
  onAnalyzeMeeting,
  onTranscribeAudio,
}: Props) {
  const [title, setTitle] = useState("");
  const [question, setQuestion] = useState("When was the day of meeting?");
  const [audioFile, setAudioFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [documentImporting, setDocumentImporting] = useState(false);
  const [documentDragActive, setDocumentDragActive] = useState(false);
  const [documentMessage, setDocumentMessage] = useState("");
  const [error, setError] = useState("");
  const analysisRunning = analysisJob?.status === "running";

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (analysisRunning || submitting) return;
    if (!authenticated) {
      setError("Sign in before queueing analysis.");
      onRequestSignIn();
      return;
    }
    if (!audioFile && !transcript.trim()) {
      setError("Add meeting audio or transcript text before queueing analysis.");
      return;
    }

    setSubmitting(true);
    setError("");

    try {
      const form = new FormData();
      form.append("title", title);
      form.append("follow_up_question", question);
      if (audioFile) {
        form.append("file", audioFile);
      } else {
        form.append("transcript", transcript);
      }

      await onAnalyzeMeeting(form);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not queue meeting analysis.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleTranscribe() {
    if (!audioFile) return;
    if (!authenticated) {
      setError("Sign in before transcribing audio.");
      onRequestSignIn();
      return;
    }
    setTranscribing(true);
    setError("");
    try {
      await onTranscribeAudio(audioFile);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not transcribe audio.");
    } finally {
      setTranscribing(false);
    }
  }

  async function handleDocumentImport(file: File | null) {
    if (!file) return;

    setDocumentMessage("");
    if (!authenticated) {
      setError("Sign in before importing a DOCX transcript.");
      return;
    }
    if (!isDocxFile(file)) {
      setError("Please drop or choose a .docx transcript file.");
      return;
    }

    setDocumentImporting(true);
    setError("");
    try {
      const result = await importTranscriptDocument(file);
      onTranscriptChange(result.transcript);
      setDocumentMessage(`${file.name} imported into transcription output.`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not import the DOCX transcript.");
    } finally {
      setDocumentImporting(false);
    }
  }

  function handleTranscriptDragEnter(event: DragEvent<HTMLDivElement>) {
    if (!hasDraggedFiles(event.dataTransfer)) return;
    event.preventDefault();
    setDocumentDragActive(true);
  }

  function handleTranscriptDragOver(event: DragEvent<HTMLDivElement>) {
    if (!hasDraggedFiles(event.dataTransfer)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    setDocumentDragActive(true);
  }

  function handleTranscriptDragLeave(event: DragEvent<HTMLDivElement>) {
    const nextTarget = event.relatedTarget;
    if (nextTarget instanceof Node && event.currentTarget.contains(nextTarget)) return;
    setDocumentDragActive(false);
  }

  function handleTranscriptDrop(event: DragEvent<HTMLDivElement>) {
    if (!hasDraggedFiles(event.dataTransfer)) return;

    event.preventDefault();
    setDocumentDragActive(false);
    void handleDocumentImport(firstFile(event.dataTransfer.files));
  }

  const analysisFileLabel =
    analysisJob?.filename || (analysisJob?.sourceType === "audio" ? "Audio upload" : "Meeting input");
  const analysisJobDetail =
    analysisJob?.status === "failed"
      ? analysisJob.error || "Analysis failed."
      : analysisJob?.status === "completed"
        ? "Meeting analysis completed and saved."
        : analysisJob
          ? `Job ${analysisJob.jobId.slice(0, 8)} is running for ${analysisFileLabel}.`
          : "";
  const queueDisabled = !authenticated || submitting || analysisRunning || (!transcript.trim() && !audioFile);

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
            disabled={!authenticated || !audioFile || transcribing}
            onClick={handleTranscribe}
          >
            {!authenticated ? "Sign in to transcribe" : transcribing ? "Transcribing..." : "Transcribe audio"}
          </button>
        </div>

        <div className="transcript-input-group">
          <div className="transcript-label-row">
            <label htmlFor="meeting-transcript">Transcription output</label>
            <span
              className="info-tooltip"
              tabIndex={0}
              aria-label="Drag a .docx file onto the transcript box to import it."
            >
              i
            </span>
          </div>
          <div
            className={`transcript-dropzone ${documentDragActive ? "drag-active" : ""}`}
            onDragEnter={handleTranscriptDragEnter}
            onDragOver={handleTranscriptDragOver}
            onDragLeave={handleTranscriptDragLeave}
            onDrop={handleTranscriptDrop}
          >
            <textarea
              id="meeting-transcript"
              value={transcript}
              onChange={(event) => onTranscriptChange(event.target.value)}
              rows={12}
              aria-busy={documentImporting}
            />
            {(documentDragActive || documentImporting) && (
              <div className="transcript-drop-overlay" aria-hidden="true">
                {documentImporting ? "Importing DOCX..." : "Drop DOCX to import"}
              </div>
            )}
          </div>
          {documentMessage && <p className="docx-import-status">{documentMessage}</p>}
        </div>

        <label>
          Ask a follow-up question
          <input value={question} onChange={(event) => setQuestion(event.target.value)} />
        </label>

        {error && <p className="error">{error}</p>}
        {analysisJob && (
          <div className={`run-status ${analysisJob.status}`} id="run-status">
            <strong>{pipelineStepLabel(analysisJob)}</strong>
            <span>{analysisJobDetail}</span>
          </div>
        )}
        <button className="button primary" disabled={queueDisabled}>
          {!authenticated
            ? "Sign in to run"
            : analysisRunning
              ? "Running pipeline..."
              : submitting
                ? "Queueing analysis..."
                : "Queue AI Meeting Agent"}
        </button>
      </form>
    </section>
  );
}
