import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import {
  clearAuth,
  deleteMeeting,
  getAuthToken,
  getCurrentUser,
  getJob,
  getJobTranscript,
  getLatestTranscriptionJob,
  getMeeting,
  getStoredUser,
  ingestMeeting,
  listMeetings,
  setUnauthorizedHandler,
  startTranscriptionJob,
  streamJobEvents,
  updateMeeting,
} from "./api";
import ActionBoard from "./components/ActionBoard";
import ActionFollowUp from "./components/ActionFollowUp";
import AuthPage from "./components/AuthPage";
import ExportButtons from "./components/ExportButtons";
import FollowUpAnswer from "./components/FollowUpAnswer";
import MeetingForm from "./components/MeetingForm";
import MeetingHistory from "./components/MeetingHistory";
import MeetingSummary from "./components/MeetingSummary";
import OperationsDashboard from "./components/OperationsDashboard";
import TranscriptionJob from "./components/TranscriptionJob";
import type {
  ActiveAnalysisJob,
  IngestResponse,
  Meeting,
  MeetingListItem,
  TranscriptionJob as TranscriptionJobState,
  User,
} from "./types";

type Page = "analyze" | "transcription" | "history" | "actions" | "operations";
type AppView = "main" | "auth";
const DEMO_EMAIL = "demo@example.com";
const TRANSCRIPTION_JOB_PARAM = "transcriptionJob";
const ANALYSIS_JOB_PARAM = "analysisJob";
const TRANSCRIPTION_TEXT_KEY = "meeting_agent_transcript";
const SAMPLE_TRANSCRIPT = `Alright, I think everyone's here now, so let's get started. Today is May 9th, 2026, and this is the weekly product sync meeting for the NoteFlow project. The main goals today are to review user feedback, discuss the AI summarization model performance, and finalize priorities for the next sprint.

First, quick updates from engineering. Last week we pushed version 2.3.1 to beta testers. The release included faster audio uploads, speaker detection improvements, and the new smart-highlight feature. Upload speed improved by around thirty-two percent on average, especially for files larger than one hour. However, we also saw an increase in memory usage on lower-end Android devices, particularly phones with four gigabytes of RAM or less.

James will finalize the Android crash fix by Tuesday. Ravi will continue testing hierarchical summarization and report updated hallucination metrics. Emily will organize the top twenty user complaints into categories for the next sprint planning session. Marcus will investigate pricing options for student subscriptions.`;

function getAccountInitials(email?: string) {
  if (!email) return "AI";

  const name = email.split("@")[0].replace(/[^a-z0-9]+/gi, " ").trim();
  const parts = name.split(/\s+/).filter(Boolean);
  const initials = parts.length > 1 ? `${parts[0][0]}${parts[1][0]}` : (parts[0] ?? email).slice(0, 2);

  return initials.toUpperCase();
}

function isBackendTimeout(caught: unknown): caught is Error {
  return caught instanceof Error && caught.message.startsWith("Backend did not respond");
}

function getStoredTranscript() {
  const storedTranscript = sessionStorage.getItem(TRANSCRIPTION_TEXT_KEY);
  return storedTranscript?.trim() ? storedTranscript : SAMPLE_TRANSCRIPT;
}

function getTranscriptionJobIdFromUrl() {
  const jobId = new URLSearchParams(window.location.search).get(TRANSCRIPTION_JOB_PARAM);
  return jobId && /^[a-f0-9]{32}$/i.test(jobId) ? jobId : null;
}

function getAnalysisJobIdFromUrl() {
  const jobId = new URLSearchParams(window.location.search).get(ANALYSIS_JOB_PARAM);
  return jobId && /^[a-f0-9]{32}$/i.test(jobId) ? jobId : null;
}

function setTranscriptionJobIdInUrl(jobId: string | null) {
  const url = new URL(window.location.href);
  if (jobId) {
    url.searchParams.set(TRANSCRIPTION_JOB_PARAM, jobId);
  } else {
    url.searchParams.delete(TRANSCRIPTION_JOB_PARAM);
  }
  window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
}

function setAnalysisJobIdInUrl(jobId: string | null) {
  const url = new URL(window.location.href);
  if (jobId) {
    url.searchParams.set(ANALYSIS_JOB_PARAM, jobId);
  } else {
    url.searchParams.delete(ANALYSIS_JOB_PARAM);
  }
  window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
}

function Intro() {
  return (
    <section className="intro">
      <div>
        <h1>AI Meeting Action Agent</h1>
        <p className="lede">
          Convert meeting transcripts into clear summaries, follow-ups, and trackable action items.
        </p>
      </div>
      <div className="workflow" aria-label="Workflow">
        <span>1. Add meeting</span>
        <span>2. Run agent</span>
        <span>3. Manage actions</span>
      </div>
    </section>
  );
}

function AuthRequiredPanel({ onSignIn }: { onSignIn: () => void }) {
  return (
    <section className="panel empty-state auth-required-panel">
      <p className="eyebrow">Sign in required</p>
      <h2>Sign in to use this workspace</h2>
      <p>Meeting history, transcription jobs, actions, and operations require a user token.</p>
      <button className="button primary" type="button" onClick={onSignIn}>
        Sign in
      </button>
    </section>
  );
}

function canViewOperations(user: User | null) {
  return user?.role === "admin";
}

function AdminRequiredPanel() {
  return (
    <section className="panel empty-state auth-required-panel">
      <p className="eyebrow">Admin dashboard</p>
      <h2>Operations is for admins</h2>
      <p>This page shows system-wide jobs, worker status, audit events, and prompt configuration across the whole database.</p>
    </section>
  );
}

export default function App() {
  const [page, setPage] = useState<Page>("analyze");
  const [meetings, setMeetings] = useState<MeetingListItem[]>([]);
  const [selectedMeeting, setSelectedMeeting] = useState<Meeting | null>(null);
  const [loadingMeetingId, setLoadingMeetingId] = useState<number | null>(null);
  const [analysisJob, setAnalysisJob] = useState<ActiveAnalysisJob | null>(null);
  const [transcriptionJob, setTranscriptionJob] = useState<TranscriptionJobState | null>(null);
  const [meetingTranscript, setMeetingTranscript] = useState(() => getStoredTranscript());
  const [analysisFormResetKey, setAnalysisFormResetKey] = useState(0);
  const [user, setUser] = useState<User | null>(getStoredUser());
  const [checkingAuth, setCheckingAuth] = useState(true);
  const [view, setView] = useState<AppView>("main");
  const [error, setError] = useState("");
  const [resultTitleEditing, setResultTitleEditing] = useState(false);
  const [resultTitleDraft, setResultTitleDraft] = useState("");
  const [resultTitleSaving, setResultTitleSaving] = useState(false);
  const [resultTitleError, setResultTitleError] = useState("");
  const deletedMeetingIds = useRef(new Set<number>());
  const activeAnalysisMonitor = useRef<string | null>(null);
  const activeTranscriptionMonitor = useRef<string | null>(null);
  const latestTranscriptionCheckedForUser = useRef<number | null>(null);
  const workspaceVersion = useRef(0);
  const isDemoAccount = user?.email === DEMO_EMAIL;

  const totalOpenActions = useMemo(
    () => meetings.reduce((total, meeting) => total + Math.max(meeting.action_count - meeting.done_count, 0), 0),
    [meetings],
  );
  const openActionLabel = `${totalOpenActions} open action${totalOpenActions === 1 ? "" : "s"}`;

  async function refreshMeetings() {
    const nextMeetings = await listMeetings();
    setMeetings(nextMeetings);
    return nextMeetings;
  }

  async function loadMeeting(id: number) {
    setLoadingMeetingId(id);
    setError("");
    try {
      const meeting = await getMeeting(id);
      if (deletedMeetingIds.current.has(id)) {
        return null;
      }
      setSelectedMeeting(meeting);
      return meeting;
    } catch (caught) {
      if (deletedMeetingIds.current.has(id)) {
        return null;
      }
      setError(caught instanceof Error ? caught.message : "Could not load meeting.");
      return null;
    } finally {
      setLoadingMeetingId(null);
    }
  }

  function resetWorkspaceState(options: { preserveJobUrls?: boolean } = {}) {
    workspaceVersion.current += 1;
    activeAnalysisMonitor.current = null;
    activeTranscriptionMonitor.current = null;
    latestTranscriptionCheckedForUser.current = null;
    deletedMeetingIds.current.clear();
    setPage("analyze");
    setMeetings([]);
    setSelectedMeeting(null);
    setLoadingMeetingId(null);
    setAnalysisJob(null);
    setTranscriptionJob(null);
    setMeetingTranscript(SAMPLE_TRANSCRIPT);
    setAnalysisFormResetKey((current) => current + 1);
    setResultTitleEditing(false);
    setResultTitleDraft("");
    setResultTitleSaving(false);
    setResultTitleError("");
    setError("");
    sessionStorage.removeItem(TRANSCRIPTION_TEXT_KEY);
    localStorage.removeItem(TRANSCRIPTION_TEXT_KEY);
    if (!options.preserveJobUrls) {
      setAnalysisJobIdInUrl(null);
      setTranscriptionJobIdInUrl(null);
    }
  }

  function activateWorkspace(nextUser: User) {
    if (user?.id !== nextUser.id) {
      resetWorkspaceState({ preserveJobUrls: user === null });
    }
    setUser(nextUser);
    setView("main");
  }

  function enterLoggedOut(message = "") {
    clearAuth();
    resetWorkspaceState({ preserveJobUrls: true });
    setUser(null);
    setView("main");
    if (message) {
      setError(message);
    }
  }

  function showAuthPage() {
    setView("auth");
  }

  function handleLogout() {
    enterLoggedOut();
  }

  useEffect(() => {
    setUnauthorizedHandler(() => {
      enterLoggedOut("Sign in to continue.");
    });
    return () => setUnauthorizedHandler(null);
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function bootWorkspace() {
      try {
        if (getAuthToken()) {
          const currentUser = await getCurrentUser();
          if (!cancelled) {
            activateWorkspace(currentUser);
          }
        } else {
          if (!cancelled) {
            enterLoggedOut();
          }
        }
      } catch (caught) {
        if (isBackendTimeout(caught)) {
          if (!cancelled) {
            setError(caught.message);
          }
          return;
        }

        if (!cancelled) {
          enterLoggedOut(caught instanceof Error ? caught.message : "Please sign in again.");
        }
      } finally {
        if (!cancelled) {
          setCheckingAuth(false);
        }
      }
    }

    bootWorkspace();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!user) return;
    refreshMeetings().catch((caught) => {
      setError(caught instanceof Error ? caught.message : "Could not load your workspace.");
    });
  }, [user?.id]);

  useEffect(() => {
    window.scrollTo({ top: 0, left: 0, behavior: "auto" });
  }, [page]);

  useEffect(() => {
    setResultTitleEditing(false);
    setResultTitleDraft(selectedMeeting?.title ?? "");
    setResultTitleError("");
  }, [selectedMeeting?.id, selectedMeeting?.title]);

  useEffect(() => {
    localStorage.removeItem("meeting_agent_transcription_job");
  }, []);

  useEffect(() => {
    sessionStorage.setItem(TRANSCRIPTION_TEXT_KEY, meetingTranscript);
  }, [meetingTranscript]);

  useEffect(() => {
    if (checkingAuth || !user) return;
    const jobId = getTranscriptionJobIdFromUrl();
    if (!jobId) return;
    setPage("transcription");
    void monitorTranscriptionJob(jobId);
  }, [checkingAuth, user?.id]);

  useEffect(() => {
    if (checkingAuth || !user) return;
    const jobId = getAnalysisJobIdFromUrl();
    if (!jobId) return;
    setPage("analyze");
    void monitorAnalysisJob(jobId);
  }, [checkingAuth, user?.id]);

  useEffect(() => {
    if (user && transcriptionJob?.status === "running" && transcriptionJob.jobId) {
      void monitorTranscriptionJob(transcriptionJob.jobId, transcriptionJob);
    }
  }, [transcriptionJob?.jobId, transcriptionJob?.status, user?.id]);

  useEffect(() => {
    if (checkingAuth || page !== "transcription" || !user || transcriptionJob || getTranscriptionJobIdFromUrl()) {
      return;
    }
    if (latestTranscriptionCheckedForUser.current === user.id) {
      return;
    }

    latestTranscriptionCheckedForUser.current = user.id;
    void restoreLatestTranscriptionJob();
  }, [checkingAuth, page, transcriptionJob?.jobId, user?.id]);

  function jobStatusToAnalysisStatus(status: string): ActiveAnalysisJob["status"] {
    if (status === "completed") return "completed";
    if (status === "failed") return "failed";
    return "running";
  }

  function mergeAnalysisJob(
    current: ActiveAnalysisJob | null,
    jobId: string,
    patch: Partial<ActiveAnalysisJob>,
  ) {
    if (current?.jobId && current.jobId !== jobId) return current;
    return {
      filename: current?.filename ?? patch.filename ?? "Meeting input",
      sourceType: current?.sourceType ?? patch.sourceType ?? "transcript",
      status: current?.status ?? "running",
      currentStep: current?.currentStep ?? patch.currentStep ?? "analysis_job_queued",
      startedAt: current?.startedAt ?? patch.startedAt ?? new Date().toISOString(),
      ...current,
      ...patch,
      jobId,
    };
  }

  function buildBaseAnalysisJob(form: FormData, queued: IngestResponse): ActiveAnalysisJob {
    const upload = form.get("file");
    const isFileUpload = upload instanceof File;
    return {
      jobId: queued.job_id,
      status: jobStatusToAnalysisStatus(queued.status),
      currentStep: queued.current_step,
      filename: isFileUpload ? upload.name : "Transcript input",
      sourceType: isFileUpload ? "audio" : "transcript",
      startedAt: new Date().toISOString(),
      meetingId: queued.meeting_id ?? null,
    };
  }

  async function applyAnalysisJobState(
    jobId: string,
    baseJob?: ActiveAnalysisJob,
    workspaceVersionAtStart = workspaceVersion.current,
  ) {
    const job = await getJob(jobId);
    if (workspaceVersion.current !== workspaceVersionAtStart) return job;
    const status = jobStatusToAnalysisStatus(job.status);
    const patch: Partial<ActiveAnalysisJob> = {
      jobId,
      filename: job.filename || baseJob?.filename,
      sourceType: job.source_type || baseJob?.sourceType,
      status,
      currentStep: job.current_step,
      startedAt: baseJob?.startedAt ?? job.created_at,
      completedAt: status === "running" ? undefined : job.updated_at,
      meetingId: job.meeting_id ?? baseJob?.meetingId ?? null,
      error: status === "failed" ? job.error_message || "Analysis failed." : undefined,
    };

    if (status === "completed") {
      setAnalysisJob((current) => mergeAnalysisJob(current ?? baseJob ?? null, jobId, patch));
      await refreshMeetings();
      if (job.meeting_id && !deletedMeetingIds.current.has(job.meeting_id)) {
        await loadMeeting(job.meeting_id);
      }
      return job;
    }

    setAnalysisJob((current) => mergeAnalysisJob(current ?? baseJob ?? null, jobId, patch));
    return job;
  }

  async function monitorAnalysisJob(jobId: string, baseJob?: ActiveAnalysisJob) {
    if (activeAnalysisMonitor.current === jobId) return;
    const workspaceVersionAtStart = workspaceVersion.current;
    activeAnalysisMonitor.current = jobId;
    try {
      const initialJob = await applyAnalysisJobState(jobId, baseJob, workspaceVersionAtStart);
      if (workspaceVersion.current !== workspaceVersionAtStart) return;
      if (initialJob.status === "completed" || initialJob.status === "failed") return;

      await streamJobEvents(jobId, (message) => {
        if (workspaceVersion.current !== workspaceVersionAtStart) return;
        const status = jobStatusToAnalysisStatus(message.job.status);
        if (status === "completed") return;
        setAnalysisJob((current) =>
          mergeAnalysisJob(current ?? baseJob ?? null, jobId, {
            filename: message.job.filename || baseJob?.filename,
            sourceType: message.job.source_type || baseJob?.sourceType,
            status,
            currentStep: message.job.current_step,
            startedAt: baseJob?.startedAt ?? message.job.created_at,
            completedAt: status === "running" ? undefined : message.job.updated_at,
            meetingId: message.job.meeting_id ?? baseJob?.meetingId ?? null,
            error: status === "failed" ? message.job.error_message || "Analysis failed." : undefined,
          }),
        );
      });
      if (workspaceVersion.current !== workspaceVersionAtStart) return;
      await applyAnalysisJobState(jobId, baseJob, workspaceVersionAtStart);
    } catch (caught) {
      if (workspaceVersion.current !== workspaceVersionAtStart) return;
      const message = caught instanceof Error ? caught.message : "Could not restore the analysis job.";
      if (/job not found|permission denied/i.test(message)) {
        if (getAnalysisJobIdFromUrl() === jobId) {
          setAnalysisJobIdInUrl(null);
        }
        setAnalysisJob((current) => (current?.jobId === jobId ? null : current));
        return;
      }
      setError(message);
    } finally {
      if (activeAnalysisMonitor.current === jobId) {
        activeAnalysisMonitor.current = null;
      }
    }
  }

  async function handleAnalyzeMeeting(form: FormData) {
    if (!user) {
      showAuthPage();
      return;
    }
    setError("");
    setAnalysisJob(null);
    setAnalysisJobIdInUrl(null);

    const queued = await ingestMeeting(form);
    const durableJob = buildBaseAnalysisJob(form, queued);
    setSelectedMeeting(null);
    setAnalysisJob(durableJob);
    setAnalysisJobIdInUrl(queued.job_id);
    window.setTimeout(() => {
      document.getElementById("run-status")?.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 0);
    void monitorAnalysisJob(queued.job_id, durableJob);
  }

  function jobStatusToTranscriptionStatus(status: string): TranscriptionJobState["status"] {
    if (status === "completed") return "completed";
    if (status === "failed") return "failed";
    return "running";
  }

  function mergeTranscriptionJob(
    current: TranscriptionJobState | null,
    jobId: string,
    patch: Partial<TranscriptionJobState>,
  ) {
    if (current?.jobId && current.jobId !== jobId) return current;
    return {
      fileName: current?.fileName ?? patch.fileName ?? "Audio upload",
      fileSize: current?.fileSize ?? patch.fileSize,
      status: current?.status ?? "running",
      startedAt: current?.startedAt ?? patch.startedAt ?? new Date().toISOString(),
      ...current,
      ...patch,
      jobId,
    };
  }

  async function applyTranscriptionJobState(
    jobId: string,
    baseJob?: TranscriptionJobState,
    workspaceVersionAtStart = workspaceVersion.current,
  ) {
    const job = await getJob(jobId);
    if (workspaceVersion.current !== workspaceVersionAtStart) return job;
    const status = jobStatusToTranscriptionStatus(job.status);
    const patch: Partial<TranscriptionJobState> = {
      jobId,
      fileName: job.filename || baseJob?.fileName,
      fileSize: baseJob?.fileSize ?? job.file_size_bytes,
      status,
      currentStep: job.current_step,
      startedAt: baseJob?.startedAt ?? job.created_at,
      completedAt: status === "running" ? undefined : job.updated_at,
      error: status === "failed" ? job.error_message || "Transcription failed." : undefined,
    };

    if (status === "completed") {
      const result = await getJobTranscript(jobId);
      if (workspaceVersion.current !== workspaceVersionAtStart) return job;
      setMeetingTranscript(result.transcript);
      patch.transcriptLength = result.transcript.length;
    }

    setTranscriptionJob((current) => mergeTranscriptionJob(current ?? baseJob ?? null, jobId, patch));
    return job;
  }

  async function monitorTranscriptionJob(jobId: string, baseJob?: TranscriptionJobState) {
    if (activeTranscriptionMonitor.current === jobId) return;
    const workspaceVersionAtStart = workspaceVersion.current;
    activeTranscriptionMonitor.current = jobId;
    try {
      const initialJob = await applyTranscriptionJobState(jobId, baseJob, workspaceVersionAtStart);
      if (workspaceVersion.current !== workspaceVersionAtStart) return;
      if (initialJob.status === "completed" || initialJob.status === "failed") return;

      await streamJobEvents(jobId, (message) => {
        if (workspaceVersion.current !== workspaceVersionAtStart) return;
        const status = jobStatusToTranscriptionStatus(message.job.status);
        setTranscriptionJob((current) =>
          mergeTranscriptionJob(current ?? baseJob ?? null, jobId, {
            status,
            currentStep: message.job.current_step,
            completedAt: status === "running" ? undefined : message.job.updated_at,
            error: status === "failed" ? message.job.error_message || "Transcription failed." : undefined,
          }),
        );
      });
      if (workspaceVersion.current !== workspaceVersionAtStart) return;
      await applyTranscriptionJobState(jobId, baseJob, workspaceVersionAtStart);
    } catch (caught) {
      if (workspaceVersion.current !== workspaceVersionAtStart) return;
      setError(caught instanceof Error ? caught.message : "Could not restore the transcription job.");
    } finally {
      if (activeTranscriptionMonitor.current === jobId) {
        activeTranscriptionMonitor.current = null;
      }
    }
  }

  async function restoreLatestTranscriptionJob() {
    const workspaceVersionAtStart = workspaceVersion.current;
    try {
      const latestJob = await getLatestTranscriptionJob();
      if (workspaceVersion.current !== workspaceVersionAtStart) return;
      if (!latestJob) return;
      const baseJob: TranscriptionJobState = {
        jobId: latestJob.job_id,
        fileName: latestJob.filename || "Audio upload",
        fileSize: latestJob.file_size_bytes,
        status: jobStatusToTranscriptionStatus(latestJob.status),
        currentStep: latestJob.current_step,
        startedAt: latestJob.created_at,
        completedAt: latestJob.status === "queued" || latestJob.status === "processing" ? undefined : latestJob.updated_at,
        error: latestJob.status === "failed" ? latestJob.error_message || "Transcription failed." : undefined,
      };
      setTranscriptionJob(baseJob);
      if (baseJob.status === "running") {
        setTranscriptionJobIdInUrl(latestJob.job_id);
      }
      await monitorTranscriptionJob(latestJob.job_id, baseJob);
    } catch (caught) {
      if (workspaceVersion.current !== workspaceVersionAtStart) return;
      latestTranscriptionCheckedForUser.current = null;
      setError(caught instanceof Error ? caught.message : "Could not load the latest transcription job.");
    }
  }

  async function handleTranscribeAudio(file: File) {
    if (!user) {
      showAuthPage();
      return;
    }
    const startedAt = new Date().toISOString();
    const baseJob: TranscriptionJobState = {
      fileName: file.name,
      fileSize: file.size,
      status: "running",
      currentStep: "transcription_queued",
      startedAt,
    };
    setError("");
    setTranscriptionJob(baseJob);
    setPage("transcription");

    try {
      const queued = await startTranscriptionJob(file);
      const durableJob = {
        ...baseJob,
        jobId: queued.job_id,
        currentStep: queued.current_step,
      };
      setTranscriptionJobIdInUrl(queued.job_id);
      setTranscriptionJob(durableJob);
      await monitorTranscriptionJob(queued.job_id, durableJob);
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "Could not start transcription.";
      setTranscriptionJob({
        ...baseJob,
        status: "failed",
        completedAt: new Date().toISOString(),
        error: message,
      });
      throw caught;
    }
  }

  async function handleHistorySelect(id: number) {
    const meeting = await loadMeeting(id);
    if (meeting) {
      setPage("history");
    }
  }

  async function handleDeleteMeeting(id: number) {
    const meeting = meetings.find((item) => item.id === id);
    const label = meeting?.title ?? "this meeting";
    const confirmed = window.confirm(`Delete "${label}" and all its actions?`);
    if (!confirmed) return;

    setError("");
    deletedMeetingIds.current.add(id);
    setMeetings((currentMeetings) => currentMeetings.filter((item) => item.id !== id));
    setLoadingMeetingId((currentId) => (currentId === id ? null : currentId));
    if (selectedMeeting?.id === id) {
      setSelectedMeeting(null);
    }
    if (analysisJob?.meetingId === id) {
      setAnalysisJob(null);
      setAnalysisJobIdInUrl(null);
    }

    try {
      await deleteMeeting(id);
      await refreshMeetings();
    } catch (caught) {
      deletedMeetingIds.current.delete(id);
      await refreshMeetings().catch(() => undefined);
      setError(caught instanceof Error ? caught.message : "Could not delete meeting.");
    }
  }

  async function handleRenameMeeting(id: number, title: string) {
    setError("");
    const updatedMeeting = await updateMeeting(id, { title });
    setSelectedMeeting(updatedMeeting);
    await refreshMeetings();
  }

  async function handleResultTitleSave(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedMeeting || resultTitleSaving) return;

    const nextTitle = resultTitleDraft.trim();
    if (!nextTitle) {
      setResultTitleError("Meeting name is required.");
      return;
    }

    setResultTitleSaving(true);
    setResultTitleError("");
    try {
      await handleRenameMeeting(selectedMeeting.id, nextTitle);
      setResultTitleEditing(false);
    } catch (caught) {
      setResultTitleError(caught instanceof Error ? caught.message : "Could not rename meeting.");
    } finally {
      setResultTitleSaving(false);
    }
  }

  async function handleActionMeetingSelect(id: number) {
    await loadMeeting(id);
  }

  async function handleActionsChanged() {
    const nextMeetings = await refreshMeetings();
    if (selectedMeeting) {
      const stillExists = nextMeetings.some((meeting) => meeting.id === selectedMeeting.id);
      if (stillExists) {
        await loadMeeting(selectedMeeting.id);
      }
    }
  }

  if (checkingAuth) {
    return (
      <main className="auth-page">
        <section className="panel empty-state">
          <h2>Loading workspace...</h2>
        </section>
      </main>
    );
  }

  if (view === "auth") {
    return (
      <AuthPage
        onCancel={() => setView("main")}
        onAuthenticated={(nextUser) => {
          activateWorkspace(nextUser);
        }}
      />
    );
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <section className={`account-card ${user ? "signed-in" : "logged-out"}`} aria-label="Workspace account">
          <div className="account-label-row">
            <span className="account-kicker">{user ? "Signed in" : "Logged out"}</span>
            {user ? (
              <span className="account-status">
                <span aria-hidden="true" className="status-dot" />
                {isDemoAccount ? "Demo account" : "Personal account"}
              </span>
            ) : (
              <span className="account-status muted-status">
                <span aria-hidden="true" className="status-dot" />
                No token
              </span>
            )}
          </div>
          <div className="account-main">
            <span className="account-avatar" aria-hidden="true">
              {user ? getAccountInitials(user.email) : "AI"}
            </span>
            <div className="account-copy">
              <strong title={user?.email ?? "Logged out"}>{user?.email ?? "Not signed in"}</strong>
              <span>{user ? openActionLabel : "Sign in to run jobs"}</span>
            </div>
          </div>
          <div className="account-footer">
            {user ? (
              <button className="account-button" onClick={handleLogout}>
                Logout
              </button>
            ) : (
              <button className="account-button primary" onClick={showAuthPage}>
                Sign in
              </button>
            )}
          </div>
        </section>
        <nav className="nav" aria-label="Main navigation">
          <button className={page === "analyze" ? "active" : ""} onClick={() => setPage("analyze")}>
            Analyze Meeting
          </button>
          <button className={page === "transcription" ? "active" : ""} onClick={() => setPage("transcription")}>
            Transcription Job
          </button>
          <button className={page === "history" ? "active" : ""} onClick={() => setPage("history")}>
            Meeting History
          </button>
          <button className={page === "actions" ? "active" : ""} onClick={() => setPage("actions")}>
            Action Follow-Up
          </button>
          <button className={page === "operations" ? "active" : ""} onClick={() => setPage("operations")}>
            Operations
          </button>
        </nav>
      </aside>

      <main className="main">
        <Intro />

        {error && <div className="notice error">{error}</div>}

        {page === "analyze" && (
          <>
            <MeetingForm
              key={analysisFormResetKey}
              transcript={meetingTranscript}
              onTranscriptChange={setMeetingTranscript}
              analysisJob={analysisJob}
              authenticated={Boolean(user)}
              onRequestSignIn={showAuthPage}
              onAnalyzeMeeting={handleAnalyzeMeeting}
              onTranscribeAudio={handleTranscribeAudio}
            />
            {user && selectedMeeting && (
              <section className="result-stack" id="agent-results">
                <div className="result-header">
                  <div>
                    <div className="detail-eyebrow-row">
                      <p className="eyebrow">Saved meeting</p>
                      <span
                        className="info-tooltip"
                        tabIndex={0}
                        aria-label="Double-click the meeting title to rename it."
                      >
                        i
                      </span>
                    </div>
                    {resultTitleEditing ? (
                      <form className="title-edit-form" onSubmit={(event) => void handleResultTitleSave(event)}>
                        <input
                          aria-label="Meeting name"
                          value={resultTitleDraft}
                          onChange={(event) => setResultTitleDraft(event.target.value)}
                        />
                        <button className="button secondary" type="submit" disabled={resultTitleSaving}>
                          {resultTitleSaving ? "Saving..." : "Save"}
                        </button>
                        <button
                          className="button secondary"
                          type="button"
                          disabled={resultTitleSaving}
                          onClick={() => {
                            setResultTitleDraft(selectedMeeting.title);
                            setResultTitleEditing(false);
                            setResultTitleError("");
                          }}
                        >
                          Cancel
                        </button>
                        {resultTitleError && <p className="error inline-error">{resultTitleError}</p>}
                      </form>
                    ) : (
                      <div className="title-display-row">
                        <button
                          className="title-rename-target"
                          type="button"
                          title="Double-click to rename"
                          aria-label="Double-click to rename meeting"
                          onDoubleClick={() => setResultTitleEditing(true)}
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
                <ActionBoard actions={selectedMeeting.actions} />
                <FollowUpAnswer
                  question={selectedMeeting.follow_up_question}
                  answer={selectedMeeting.follow_up_answer}
                  sources={selectedMeeting.follow_up_sources}
                />
                <MeetingSummary meeting={selectedMeeting} />
              </section>
            )}
          </>
        )}

        {page === "transcription" && (
          user ? (
            <TranscriptionJob
              job={transcriptionJob}
              transcript={meetingTranscript}
              onBackToAnalyze={() => {
                if (transcriptionJob?.status !== "running") {
                  setTranscriptionJobIdInUrl(null);
                }
                setPage("analyze");
              }}
            />
          ) : (
            <AuthRequiredPanel onSignIn={showAuthPage} />
          )
        )}

        {page === "history" && (
          user ? (
            <MeetingHistory
              meetings={meetings}
              selectedMeeting={selectedMeeting}
              analysisJob={analysisJob}
              loadingMeetingId={loadingMeetingId}
              onSelect={handleHistorySelect}
              onDelete={handleDeleteMeeting}
              onRename={handleRenameMeeting}
            />
          ) : (
            <AuthRequiredPanel onSignIn={showAuthPage} />
          )
        )}

        {page === "actions" && (
          user ? (
            <ActionFollowUp
              meetings={meetings}
              selectedMeeting={selectedMeeting}
              loadingMeetingId={loadingMeetingId}
              onSelectMeeting={handleActionMeetingSelect}
              onChanged={handleActionsChanged}
            />
          ) : (
            <AuthRequiredPanel onSignIn={showAuthPage} />
          )
        )}

        {page === "operations" && (
          user ? (
            canViewOperations(user) ? (
              <OperationsDashboard />
            ) : (
              <AdminRequiredPanel />
            )
          ) : (
            <AuthRequiredPanel onSignIn={showAuthPage} />
          )
        )}
      </main>
    </div>
  );
}
