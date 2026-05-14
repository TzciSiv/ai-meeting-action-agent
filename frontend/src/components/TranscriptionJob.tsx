import { useEffect, useState } from "react";
import type { TranscriptionJob as TranscriptionJobState } from "../types";

interface Props {
  job: TranscriptionJobState | null;
  transcript: string;
  onBackToAnalyze: () => void;
}

function formatFileSize(bytes: number) {
  if (bytes < 1024 * 1024) {
    return `${Math.max(bytes / 1024, 1).toFixed(1)} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatTime(value?: string) {
  if (!value) return "";
  return new Intl.DateTimeFormat(undefined, {
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(value));
}

function statusLabel(status: TranscriptionJobState["status"]) {
  if (status === "running") return "Running";
  if (status === "completed") return "Complete";
  return "Failed";
}

function getRunningStep(job: TranscriptionJobState, processingDelayElapsed: boolean) {
  if (job.status !== "running") return formatTime(job.completedAt);
  return processingDelayElapsed ? "Processing by Whisper" : "Sending audio to Whisper";
}

function getTranscriptFileName(job: TranscriptionJobState) {
  const baseName = job.fileName
    .replace(/\.[^/.]+$/, "")
    .replace(/[\\/:*?"<>|]+/g, "-")
    .trim();

  return `${baseName || "meeting"}_transcript.txt`;
}

function downloadTranscript(job: TranscriptionJobState, transcript: string) {
  const blob = new Blob([transcript], { type: "text/plain;charset=utf-8" });
  const url = window.URL.createObjectURL(blob);
  const link = document.createElement("a");

  link.href = url;
  link.download = getTranscriptFileName(job);
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
}

export default function TranscriptionJob({ job, transcript, onBackToAnalyze }: Props) {
  const [processingDelayElapsed, setProcessingDelayElapsed] = useState(false);

  useEffect(() => {
    if (!job || job.status !== "running") {
      setProcessingDelayElapsed(false);
      return;
    }

    const startedAt = new Date(job.startedAt).getTime();
    const remainingDelay = Math.max(startedAt + 5000 - Date.now(), 0);
    setProcessingDelayElapsed(remainingDelay === 0);

    const timer = window.setTimeout(() => {
      setProcessingDelayElapsed(true);
    }, remainingDelay);

    return () => window.clearTimeout(timer);
  }, [job?.startedAt, job?.status]);

  if (!job) {
    return (
      <section className="panel empty-state">
        <h2>No transcription job yet</h2>
        <p>Upload an audio file and start transcription from the meeting input page.</p>
        <button className="button primary" type="button" onClick={onBackToAnalyze}>
          Go to meeting input
        </button>
      </section>
    );
  }

  return (
    <section className="transcription-page">
      <div className="panel transcription-job-panel">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Audio transcription</p>
            <h2>Transcription Job</h2>
          </div>
          <span className={`job-status ${job.status}`}>{statusLabel(job.status)}</span>
        </div>

        {job.status === "running" && (
          <div className="job-progress" aria-label="Transcription job is running">
            <span />
          </div>
        )}

        <div className="job-detail-grid">
          <div>
            <span>File</span>
            <strong>{job.fileName}</strong>
          </div>
          <div>
            <span>Size</span>
            <strong>{formatFileSize(job.fileSize)}</strong>
          </div>
          <div>
            <span>Started</span>
            <strong>{formatTime(job.startedAt)}</strong>
          </div>
          <div>
            <span>{job.status === "running" ? "Current step" : "Finished"}</span>
            <strong>{getRunningStep(job, processingDelayElapsed)}</strong>
          </div>
        </div>

        {job.status === "completed" && (
          <div className="job-result success">
            <h3>Transcript is ready</h3>
            <p>{job.transcriptLength ?? 0} characters were added to the transcript field.</p>
          </div>
        )}

        {job.status === "failed" && (
          <div className="job-result failed">
            <h3>Transcription failed</h3>
            <p>{job.error}</p>
          </div>
        )}

        <div className="job-actions">
          {job.status === "completed" && transcript.trim() && (
            <button className="button primary" type="button" onClick={() => downloadTranscript(job, transcript)}>
              Download transcript
            </button>
          )}
          <button
            className={`button ${job.status === "completed" && !transcript.trim() ? "primary" : "secondary"}`}
            type="button"
            onClick={onBackToAnalyze}
          >
            Back to meeting input
          </button>
        </div>
      </div>
    </section>
  );
}
