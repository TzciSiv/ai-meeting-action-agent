import { useEffect, useState, type FormEvent } from "react";
import ExportButtons from "./ExportButtons";
import FollowUpAnswer from "./FollowUpAnswer";
import MeetingSummary from "./MeetingSummary";
import type { ActiveAnalysisJob, Meeting, MeetingListItem } from "../types";

interface Props {
  meetings: MeetingListItem[];
  selectedMeeting: Meeting | null;
  analysisJob: ActiveAnalysisJob | null;
  loadingMeetingId: number | null;
  onSelect: (id: number) => Promise<void>;
  onDelete: (id: number) => Promise<void>;
  onRename: (id: number, title: string) => Promise<void>;
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

function pipelineStepLabel(job: Pick<ActiveAnalysisJob, "currentStep">) {
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
  return labels[job.currentStep] ?? job.currentStep.replace(/_/g, " ");
}

function jobCopy(job: ActiveAnalysisJob) {
  if (job.status === "failed") {
    return job.error || "Analysis failed.";
  }
  return `Job ${job.jobId.slice(0, 8)} is still analyzing this meeting. Results will appear here when it finishes.`;
}

export default function MeetingHistory({
  meetings,
  selectedMeeting,
  analysisJob,
  loadingMeetingId,
  onSelect,
  onDelete,
  onRename,
}: Props) {
  const [editingTitle, setEditingTitle] = useState(false);
  const [draftTitle, setDraftTitle] = useState("");
  const [savingTitle, setSavingTitle] = useState(false);
  const [titleError, setTitleError] = useState("");

  useEffect(() => {
    setEditingTitle(false);
    setDraftTitle(selectedMeeting?.title ?? "");
    setTitleError("");
  }, [selectedMeeting?.id, selectedMeeting?.title]);

  async function saveTitle(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedMeeting || savingTitle) return;

    const nextTitle = draftTitle.trim();
    if (!nextTitle) {
      setTitleError("Meeting name is required.");
      return;
    }

    setSavingTitle(true);
    setTitleError("");
    try {
      await onRename(selectedMeeting.id, nextTitle);
      setEditingTitle(false);
    } catch (caught) {
      setTitleError(caught instanceof Error ? caught.message : "Could not rename meeting.");
    } finally {
      setSavingTitle(false);
    }
  }

  function activeJobForMeeting(meetingId: number) {
    return analysisJob?.meetingId === meetingId && analysisJob.status !== "completed" ? analysisJob : null;
  }

  const selectedAnalysisJob = selectedMeeting ? activeJobForMeeting(selectedMeeting.id) : null;
  const showCompletedAnalysis = !selectedAnalysisJob;

  return (
    <section className="page-grid">
      <div className="panel list-panel">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Saved work</p>
            <h2>Meeting History</h2>
          </div>
          <span>{meetings.length} meetings</span>
        </div>

        {meetings.length === 0 ? (
          <p className="muted">Analyze a meeting to start building history.</p>
        ) : (
          <div className="meeting-list">
            {meetings.map((meeting) => (
              <div key={meeting.id} className={selectedMeeting?.id === meeting.id ? "meeting-row active" : "meeting-row"}>
                <button className="meeting-row-main" onClick={() => onSelect(meeting.id)}>
                  <strong>{meeting.title}</strong>
                  <span>{formatDate(meeting.created_at)}</span>
                  {activeJobForMeeting(meeting.id) ? (
                    <small>{activeJobForMeeting(meeting.id)?.status === "failed" ? "Analysis failed" : "Analyzing meeting..."}</small>
                  ) : (
                    <small>
                      {meeting.done_count}/{meeting.action_count} actions done
                    </small>
                  )}
                  {loadingMeetingId === meeting.id && <small>Loading...</small>}
                </button>
                <button
                  className="meeting-delete"
                  title="Delete meeting"
                  aria-label={`Delete ${meeting.title}`}
                  onClick={(event) => {
                    event.stopPropagation();
                    void onDelete(meeting.id);
                  }}
                >
                  <span aria-hidden="true" className="delete-x" />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="history-detail">
        {selectedMeeting ? (
          <>
            <div className="result-header compact">
              <div>
                <div className="detail-eyebrow-row">
                  <p className="eyebrow">Meeting detail</p>
                  <span
                    className="info-tooltip"
                    tabIndex={0}
                    aria-label="Double-click the meeting title to rename it."
                  >
                    i
                  </span>
                </div>
                {editingTitle ? (
                  <form className="title-edit-form" onSubmit={(event) => void saveTitle(event)}>
                    <input
                      aria-label="Meeting name"
                      value={draftTitle}
                      onChange={(event) => setDraftTitle(event.target.value)}
                    />
                    <button className="button secondary" type="submit" disabled={savingTitle}>
                      {savingTitle ? "Saving..." : "Save"}
                    </button>
                    <button
                      className="button secondary"
                      type="button"
                      disabled={savingTitle}
                      onClick={() => {
                        setDraftTitle(selectedMeeting.title);
                        setEditingTitle(false);
                        setTitleError("");
                      }}
                    >
                      Cancel
                    </button>
                    {titleError && <p className="error inline-error">{titleError}</p>}
                  </form>
                ) : (
                  <div className="title-display-row">
                    <button
                      className="title-rename-target"
                      type="button"
                      title="Double-click to rename"
                      aria-label="Double-click to rename meeting"
                      onDoubleClick={() => setEditingTitle(true)}
                    >
                      <h2>{selectedMeeting.title}</h2>
                    </button>
                  </div>
                )}
                {selectedMeeting.run_id && (
                  <p className="run-id-line">
                    Run ID <code>{selectedMeeting.run_id}</code>
                  </p>
                )}
              </div>
              <ExportButtons meetingId={selectedMeeting.id} />
            </div>
            {selectedAnalysisJob && (
              <div className={`run-status ${selectedAnalysisJob.status}`}>
                <strong>{pipelineStepLabel(selectedAnalysisJob)}</strong>
                <span>{jobCopy(selectedAnalysisJob)}</span>
              </div>
            )}
            {showCompletedAnalysis && (
              <>
                <FollowUpAnswer
                  question={selectedMeeting.follow_up_question}
                  answer={selectedMeeting.follow_up_answer}
                  sources={selectedMeeting.follow_up_sources}
                />
                <MeetingSummary meeting={selectedMeeting} />
              </>
            )}
            <details className="panel transcript-panel">
              <summary>Transcript</summary>
              <p>{selectedMeeting.transcript}</p>
            </details>
          </>
        ) : (
          <div className="panel empty-state">
            <h2>Select a meeting</h2>
            <p>Saved summaries, transcript downloads, and report exports will appear here.</p>
          </div>
        )}
      </div>
    </section>
  );
}
