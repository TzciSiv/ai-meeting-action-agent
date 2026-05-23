import type {
  ActionItem,
  ActionUpdate,
  AuditEventPage,
  AiRun,
  AuthResponse,
  IngestResponse,
  IngestionJob,
  JobEventMessage,
  Meeting,
  MeetingListItem,
  MeetingUpdate,
  MetricsSnapshot,
  PipelineOperations,
  PromptGovernanceItem,
  TranscriptResponse,
  User,
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
const AUTH_REQUEST_TIMEOUT_MS = 6000;
const TOKEN_KEY = "meeting_agent_token";
const USER_KEY = "meeting_agent_user";

let unauthorizedHandler: (() => void) | null = null;

function clearLegacySharedAuth() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
  localStorage.removeItem("meeting_agent_session_mode");
}

export function setUnauthorizedHandler(handler: (() => void) | null) {
  unauthorizedHandler = handler;
}

export function getAuthToken(): string {
  return sessionStorage.getItem(TOKEN_KEY) ?? "";
}

export function getStoredUser(): User | null {
  const stored = sessionStorage.getItem(USER_KEY);
  if (!stored) return null;
  try {
    return JSON.parse(stored) as User;
  } catch {
    return null;
  }
}

export function storeAuth(auth: AuthResponse) {
  clearLegacySharedAuth();
  sessionStorage.setItem(TOKEN_KEY, auth.access_token);
  sessionStorage.setItem(USER_KEY, JSON.stringify(auth.user));
}

export function clearAuth() {
  clearLegacySharedAuth();
  sessionStorage.removeItem(TOKEN_KEY);
  sessionStorage.removeItem(USER_KEY);
}

function authHeaders(): HeadersInit {
  const token = getAuthToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function parseError(response: Response): Promise<string> {
  let message = await response.text();
  try {
    const parsed = JSON.parse(message) as { detail?: string };
    message = parsed.detail ?? message;
  } catch {
    // Keep the plain text response.
  }
  return message || `Request failed with ${response.status}`;
}

async function fetchWithTimeout(url: string, options: RequestInit, timeoutMs?: number): Promise<Response> {
  if (!timeoutMs) {
    return fetch(url, options);
  }

  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);

  try {
    return await fetch(url, {
      ...options,
      signal: controller.signal,
    });
  } catch (caught) {
    if (caught instanceof DOMException && caught.name === "AbortError") {
      throw new Error("Backend did not respond. Restart the backend server and refresh the page.");
    }
    throw caught;
  } finally {
    window.clearTimeout(timer);
  }
}

async function request<T>(path: string, options: RequestInit = {}, timeoutMs?: number): Promise<T> {
  const response = await fetchWithTimeout(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
      ...(options.headers ?? {}),
    },
    ...options,
  }, timeoutMs);

  if (!response.ok) {
    if (response.status === 401) {
      clearAuth();
      unauthorizedHandler?.();
    }
    throw new Error(await parseError(response));
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}

async function downloadFile(path: string, filename: string): Promise<void> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: authHeaders(),
  });

  if (!response.ok) {
    if (response.status === 401) {
      clearAuth();
      unauthorizedHandler?.();
    }
    throw new Error(await parseError(response));
  }

  const blob = await response.blob();
  const url = window.URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
}

export function register(email: string, password: string): Promise<AuthResponse> {
  return request<AuthResponse>("/api/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export function login(email: string, password: string): Promise<AuthResponse> {
  return request<AuthResponse>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export function startDemoSession(): Promise<AuthResponse> {
  return request<AuthResponse>("/api/auth/demo", {
    method: "POST",
  }, AUTH_REQUEST_TIMEOUT_MS);
}

export function getCurrentUser(): Promise<User> {
  return request<User>("/api/auth/me", {}, AUTH_REQUEST_TIMEOUT_MS);
}

export async function ingestMeeting(form: FormData): Promise<IngestResponse> {
  const response = await fetch(`${API_BASE}/api/meetings/ingest`, {
    method: "POST",
    headers: authHeaders(),
    body: form,
  });

  if (!response.ok) {
    if (response.status === 401) {
      clearAuth();
      unauthorizedHandler?.();
    }
    throw new Error(await parseError(response));
  }

  return response.json() as Promise<IngestResponse>;
}

export function getJob(jobId: string): Promise<IngestionJob> {
  return request<IngestionJob>(`/api/jobs/${jobId}`);
}

export function getLatestTranscriptionJob(): Promise<IngestionJob | null> {
  return request<IngestionJob | null>("/api/jobs/latest/transcription");
}

export function getJobTranscript(jobId: string): Promise<TranscriptResponse> {
  return request<TranscriptResponse>(`/api/jobs/${jobId}/transcript`);
}

export async function streamJobEvents(
  jobId: string,
  onEvent: (message: JobEventMessage, eventType: string) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`${API_BASE}/api/jobs/${jobId}/events`, {
    headers: authHeaders(),
    signal,
  });

  if (!response.ok) {
    if (response.status === 401) {
      clearAuth();
      unauthorizedHandler?.();
    }
    throw new Error(await parseError(response));
  }

  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error("Pipeline status stream is unavailable.");
  }

  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let splitIndex = buffer.indexOf("\n\n");
    while (splitIndex !== -1) {
      const block = buffer.slice(0, splitIndex);
      buffer = buffer.slice(splitIndex + 2);
      const eventType = block.match(/^event: (.+)$/m)?.[1] ?? "message";
      const data = block.match(/^data: (.+)$/m)?.[1];
      if (data) {
        onEvent(JSON.parse(data) as JobEventMessage, eventType);
      }
      splitIndex = buffer.indexOf("\n\n");
    }
  }
}

export async function startTranscriptionJob(file: File): Promise<IngestResponse> {
  const form = new FormData();
  form.append("file", file);

  const response = await fetch(`${API_BASE}/api/meetings/transcribe/jobs`, {
    method: "POST",
    headers: authHeaders(),
    body: form,
  });

  if (!response.ok) {
    if (response.status === 401) {
      clearAuth();
      unauthorizedHandler?.();
    }
    throw new Error(await parseError(response));
  }

  return response.json() as Promise<IngestResponse>;
}

export async function importTranscriptDocument(file: File): Promise<TranscriptResponse> {
  const form = new FormData();
  form.append("file", file);

  const response = await fetch(`${API_BASE}/api/meetings/import-transcript`, {
    method: "POST",
    headers: authHeaders(),
    body: form,
  });

  if (!response.ok) {
    if (response.status === 401) {
      clearAuth();
      unauthorizedHandler?.();
    }
    throw new Error(await parseError(response));
  }

  return response.json() as Promise<TranscriptResponse>;
}

export function listMeetings(): Promise<MeetingListItem[]> {
  return request<MeetingListItem[]>("/api/meetings");
}

export function getMeeting(id: number): Promise<Meeting> {
  return request<Meeting>(`/api/meetings/${id}`);
}

export function updateMeeting(id: number, payload: MeetingUpdate): Promise<Meeting> {
  return request<Meeting>(`/api/meetings/${id}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function addAction(meetingId: number, payload: ActionUpdate & { task: string }): Promise<ActionItem> {
  return request<ActionItem>(`/api/meetings/${meetingId}/actions`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateAction(id: number, payload: ActionUpdate): Promise<ActionItem> {
  return request<ActionItem>(`/api/actions/${id}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function deleteAction(id: number): Promise<void> {
  return request<void>(`/api/actions/${id}`, {
    method: "DELETE",
  });
}

export function deleteMeeting(id: number): Promise<void> {
  return request<void>(`/api/meetings/${id}`, {
    method: "DELETE",
  });
}

export function downloadMeetingReport(id: number): Promise<void> {
  return downloadFile(`/api/meetings/${id}/export`, `meeting_${id}_report.docx`);
}

export function downloadTranscript(id: number): Promise<void> {
  return downloadFile(`/api/meetings/${id}/transcript`, `meeting_${id}_transcript.docx`);
}

export function getOperationalMetrics(): Promise<MetricsSnapshot> {
  return request<MetricsSnapshot>("/api/metrics");
}

export function getPipelineOperations(): Promise<PipelineOperations> {
  return request<PipelineOperations>("/api/operations/pipeline");
}

export function getPromptGovernance(): Promise<PromptGovernanceItem[]> {
  return request<PromptGovernanceItem[]>("/api/governance/prompts");
}

export function listAuditEvents(page = 1, pageSize = 20): Promise<AuditEventPage> {
  return request<AuditEventPage>(`/api/audit/events?page=${page}&page_size=${pageSize}`);
}

export function getAiRun(runId: string): Promise<AiRun> {
  return request<AiRun>(`/api/ai/runs/${runId}`);
}
