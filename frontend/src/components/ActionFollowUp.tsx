import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { addAction, deleteAction, updateAction } from "../api";
import type { ActionItem, ActionStatus, Meeting, MeetingListItem } from "../types";

interface Props {
  meetings: MeetingListItem[];
  selectedMeeting: Meeting | null;
  loadingMeetingId: number | null;
  onSelectMeeting: (id: number) => Promise<void>;
  onChanged: () => Promise<void>;
}

const statuses: ActionStatus[] = ["Open", "In Progress", "Done"];

function ActionEditor({ action, onChanged }: { action: ActionItem; onChanged: () => Promise<void> }) {
  const [task, setTask] = useState(action.task);
  const [owner, setOwner] = useState(action.owner);
  const [deadline, setDeadline] = useState(action.deadline);
  const [status, setStatus] = useState<ActionStatus>(action.status);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const saveVersion = useRef(0);
  const onChangedRef = useRef(onChanged);

  useEffect(() => {
    onChangedRef.current = onChanged;
  }, [onChanged]);

  useEffect(() => {
    setTask(action.task);
    setOwner(action.owner);
    setDeadline(action.deadline);
  }, [action.deadline, action.id, action.owner, action.task]);

  useEffect(() => {
    setStatus(action.status);
  }, [action.id, action.status]);

  useEffect(() => {
    const hasChanges = task !== action.task || owner !== action.owner || deadline !== action.deadline;
    if (!hasChanges) return;

    if (!task.trim()) {
      setError("Task is required.");
      return;
    }

    const version = ++saveVersion.current;
    const timer = window.setTimeout(async () => {
      setSaving(true);
      setError("");
      try {
        await updateAction(action.id, {
          task: task.trim(),
          owner: owner.trim() || "Unassigned",
          deadline: deadline.trim() || "Not mentioned",
        });
        if (saveVersion.current === version) {
          await onChangedRef.current();
        }
      } catch (caught) {
        if (saveVersion.current === version) {
          setError(caught instanceof Error ? caught.message : "Could not save action.");
        }
      } finally {
        if (saveVersion.current === version) {
          setSaving(false);
        }
      }
    }, 700);

    return () => window.clearTimeout(timer);
  }, [action.deadline, action.id, action.owner, action.task, deadline, owner, task]);

  async function saveStatus(nextStatus: ActionStatus) {
    const previousStatus = status;
    setStatus(nextStatus);
    setSaving(true);
    setError("");
    try {
      await updateAction(action.id, { status: nextStatus });
      await onChanged();
    } catch (caught) {
      setStatus(previousStatus);
      setError(caught instanceof Error ? caught.message : "Could not update status.");
    } finally {
      setSaving(false);
    }
  }

  async function removeAction() {
    setSaving(true);
    setError("");
    try {
      await deleteAction(action.id);
      await onChanged();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not delete action.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="action-editor">
      <div className="editor-main">
        <label>
          Task
          <input value={task} onChange={(event) => setTask(event.target.value)} />
        </label>
        <div className="editor-grid">
          <label>
            Owner
            <input value={owner} onChange={(event) => setOwner(event.target.value)} />
          </label>
          <label>
            Deadline
            <input value={deadline} onChange={(event) => setDeadline(event.target.value)} />
          </label>
          <label>
            Status
            <select
              value={status}
              disabled={saving}
              onChange={(event) => void saveStatus(event.target.value as ActionStatus)}
            >
              {statuses.map((value) => (
                <option key={value}>{value}</option>
              ))}
            </select>
          </label>
        </div>
        {error && <p className="error">{error}</p>}
      </div>
      <div className="editor-actions">
        {saving && <span className="save-indicator">Saving...</span>}
        <button className="button danger" type="button" disabled={saving} onClick={removeAction}>
          Delete
        </button>
      </div>
    </div>
  );
}

export default function ActionFollowUp({
  meetings,
  selectedMeeting,
  loadingMeetingId,
  onSelectMeeting,
  onChanged,
}: Props) {
  const [task, setTask] = useState("");
  const [owner, setOwner] = useState("");
  const [deadline, setDeadline] = useState("");
  const [error, setError] = useState("");
  const selectedId = selectedMeeting?.id ?? meetings[0]?.id;

  const statusCounts = useMemo(() => {
    const counts: Record<ActionStatus, number> = { Open: 0, "In Progress": 0, Done: 0 };
    selectedMeeting?.actions.forEach((action) => {
      counts[action.status] += 1;
    });
    return counts;
  }, [selectedMeeting]);

  const newestActions = useMemo(
    () =>
      [...(selectedMeeting?.actions ?? [])].sort(
        (left, right) => new Date(right.created_at).getTime() - new Date(left.created_at).getTime(),
      ),
    [selectedMeeting?.actions],
  );

  async function handleAddAction(event: FormEvent) {
    event.preventDefault();
    if (!selectedMeeting || !task.trim()) return;

    setError("");
    try {
      await addAction(selectedMeeting.id, {
        task,
        owner: owner || "Unassigned",
        deadline: deadline || "Not mentioned",
        status: "Open",
      });
      setTask("");
      setOwner("");
      setDeadline("");
      await onChanged();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not add action.");
    }
  }

  useEffect(() => {
    if (!selectedMeeting && meetings.length > 0 && loadingMeetingId === null) {
      onSelectMeeting(meetings[0].id);
    }
  }, [loadingMeetingId, meetings, onSelectMeeting, selectedMeeting]);

  return (
    <section className="action-page">
      <div className="panel action-toolbar">
        <div>
          <p className="eyebrow">Persistent tasks</p>
          <h2>Action Follow-Up</h2>
          <p className="muted">Add, edit, complete, or delete action items saved for each meeting.</p>
        </div>
        <label>
          Meeting
          <select
            value={selectedId ?? ""}
            onChange={(event) => onSelectMeeting(Number(event.target.value))}
            disabled={meetings.length === 0}
          >
            {meetings.map((meeting) => (
              <option value={meeting.id} key={meeting.id}>
                {meeting.title}
              </option>
            ))}
          </select>
        </label>
      </div>

      {!selectedMeeting ? (
        <div className="panel empty-state">
          <h2>{loadingMeetingId ? "Loading meeting..." : "No meeting selected"}</h2>
          <p>Analyze a meeting first, then return here to manage its action board.</p>
        </div>
      ) : (
        <>
          <div className="metric-row">
            <div className="metric">
              <span>Open</span>
              <strong>{statusCounts.Open}</strong>
            </div>
            <div className="metric">
              <span>In Progress</span>
              <strong>{statusCounts["In Progress"]}</strong>
            </div>
            <div className="metric">
              <span>Done</span>
              <strong>{statusCounts.Done}</strong>
            </div>
          </div>

          <form className="panel add-action-form" onSubmit={handleAddAction}>
            <label>
              New action
              <input value={task} onChange={(event) => setTask(event.target.value)} placeholder="Send follow-up notes" />
            </label>
            <label>
              Owner
              <input value={owner} onChange={(event) => setOwner(event.target.value)} placeholder="Unassigned" />
            </label>
            <label>
              Deadline
              <input value={deadline} onChange={(event) => setDeadline(event.target.value)} placeholder="Not mentioned" />
            </label>
            <button className="button primary" disabled={!task.trim()}>
              Add action
            </button>
            {error && <p className="error">{error}</p>}
          </form>

          <div className="action-edit-list">
            {newestActions.map((action) => (
              <ActionEditor key={action.id} action={action} onChanged={onChanged} />
            ))}
          </div>
        </>
      )}
    </section>
  );
}
