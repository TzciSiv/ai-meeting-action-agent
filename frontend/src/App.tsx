import { useEffect, useMemo, useRef, useState } from "react";
import {
  clearAuth,
  deleteMeeting,
  getAuthToken,
  getCurrentUser,
  getMeeting,
  getStoredSessionMode,
  getStoredUser,
  listMeetings,
  setUnauthorizedHandler,
  startDemoSession,
  storeAuth,
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
import TranscriptionJob from "./components/TranscriptionJob";
import type { Meeting, MeetingListItem, TranscriptionJob as TranscriptionJobState, User } from "./types";
import type { SessionMode } from "./api";

type Page = "analyze" | "transcription" | "history" | "actions";
type AppView = "main" | "auth";
const DEMO_EMAIL = "demo@example.com";
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

function inferSessionMode(user: User | null): SessionMode {
  const storedMode = getStoredSessionMode();
  if (storedMode) return storedMode;
  return user?.email && user.email !== DEMO_EMAIL ? "signed-in" : "demo";
}

function isBackendTimeout(caught: unknown): caught is Error {
  return caught instanceof Error && caught.message.startsWith("Backend did not respond");
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

export default function App() {
  const [page, setPage] = useState<Page>("analyze");
  const [meetings, setMeetings] = useState<MeetingListItem[]>([]);
  const [selectedMeeting, setSelectedMeeting] = useState<Meeting | null>(null);
  const [loadingMeetingId, setLoadingMeetingId] = useState<number | null>(null);
  const [transcriptionJob, setTranscriptionJob] = useState<TranscriptionJobState | null>(null);
  const [meetingTranscript, setMeetingTranscript] = useState(SAMPLE_TRANSCRIPT);
  const [user, setUser] = useState<User | null>(getStoredUser());
  const [sessionMode, setSessionMode] = useState<SessionMode>(() => inferSessionMode(getStoredUser()));
  const [checkingAuth, setCheckingAuth] = useState(true);
  const [view, setView] = useState<AppView>("main");
  const [error, setError] = useState("");
  const deletedMeetingIds = useRef(new Set<number>());
  const isDemoWorkspace = sessionMode === "demo";
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

  async function startDemoWorkspace() {
    const auth = await startDemoSession();
    storeAuth(auth, "demo");
    setUser(auth.user);
    setSessionMode("demo");
    setView("main");
    setError("");
  }

  async function handleLogout() {
    clearAuth();
    setMeetings([]);
    setSelectedMeeting(null);
    setError("");
    await startDemoWorkspace();
  }

  useEffect(() => {
    setUnauthorizedHandler(() => {
      void startDemoWorkspace();
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
            setUser(currentUser);
            setSessionMode(inferSessionMode(currentUser));
          }
        } else {
          const auth = await startDemoSession();
          storeAuth(auth, "demo");
          if (!cancelled) {
            setUser(auth.user);
            setSessionMode("demo");
          }
        }
      } catch (caught) {
        if (isBackendTimeout(caught)) {
          if (!cancelled) {
            setError(caught.message);
          }
          return;
        }

        try {
          const auth = await startDemoSession();
          storeAuth(auth, "demo");
          if (!cancelled) {
            setUser(auth.user);
            setSessionMode("demo");
          }
        } catch {
          if (!cancelled) {
            setError(caught instanceof Error ? caught.message : "Could not load the demo workspace.");
          }
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

  async function handleAnalyzed(meeting: Meeting) {
    setSelectedMeeting(meeting);
    await refreshMeetings();
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
        onContinueDemo={() => void startDemoWorkspace()}
        onAuthenticated={(nextUser) => {
          setUser(nextUser);
          setSessionMode("signed-in");
          setView("main");
          setSelectedMeeting(null);
        }}
      />
    );
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <section className={`account-card ${isDemoWorkspace ? "demo" : "signed-in"}`} aria-label="Workspace account">
          <div className="account-label-row">
            <span className="account-kicker">{isDemoWorkspace ? "Demo mode" : "Signed in"}</span>
            {!isDemoWorkspace && (
              <span className="account-status">
                <span aria-hidden="true" className="status-dot" />
                {isDemoAccount ? "Demo account" : "Private workspace"}
              </span>
            )}
          </div>
          <div className="account-main">
            <span className="account-avatar" aria-hidden="true">
              {isDemoWorkspace ? "D" : getAccountInitials(user?.email)}
            </span>
            <div className="account-copy">
              <strong title={isDemoWorkspace ? "Demo workspace" : user?.email}>
                {isDemoWorkspace ? "Demo workspace" : user?.email}
              </strong>
              <span>{isDemoWorkspace ? "Shared sample workspace" : openActionLabel}</span>
            </div>
          </div>
          <div className="account-footer">
            {isDemoWorkspace && <span className="account-stat">{openActionLabel}</span>}
            {isDemoWorkspace ? (
              <button className="account-button primary" onClick={() => setView("auth")}>
                Sign in
              </button>
            ) : (
              <button className="account-button" onClick={() => void handleLogout()}>
                Logout
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
        </nav>
      </aside>

      <main className="main">
        <Intro />

        {error && <div className="notice error">{error}</div>}

        {page === "analyze" && (
          <>
            <MeetingForm
              transcript={meetingTranscript}
              onTranscriptChange={setMeetingTranscript}
              onAnalyze={handleAnalyzed}
              onShowTranscriptionJob={() => setPage("transcription")}
              onTranscriptionJobChange={setTranscriptionJob}
            />
            {selectedMeeting && (
              <section className="result-stack" id="agent-results">
                <div className="result-header">
                  <div>
                    <p className="eyebrow">Saved meeting</p>
                    <h2>{selectedMeeting.title}</h2>
                  </div>
                  <ExportButtons meetingId={selectedMeeting.id} />
                </div>
                <ActionBoard actions={selectedMeeting.actions} />
                <FollowUpAnswer question={selectedMeeting.follow_up_question} answer={selectedMeeting.follow_up_answer} />
                <MeetingSummary meeting={selectedMeeting} />
              </section>
            )}
          </>
        )}

        {page === "transcription" && (
          <TranscriptionJob
            job={transcriptionJob}
            transcript={meetingTranscript}
            onBackToAnalyze={() => setPage("analyze")}
          />
        )}

        {page === "history" && (
          <MeetingHistory
            meetings={meetings}
            selectedMeeting={selectedMeeting}
            loadingMeetingId={loadingMeetingId}
            onSelect={handleHistorySelect}
            onDelete={handleDeleteMeeting}
            onRename={handleRenameMeeting}
          />
        )}

        {page === "actions" && (
          <ActionFollowUp
            meetings={meetings}
            selectedMeeting={selectedMeeting}
            loadingMeetingId={loadingMeetingId}
            onSelectMeeting={handleActionMeetingSelect}
            onChanged={handleActionsChanged}
          />
        )}
      </main>
    </div>
  );
}
