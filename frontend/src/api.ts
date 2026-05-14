import type {
  ActionItem,
  ActionUpdate,
  AnalyzeRequest,
  AuthResponse,
  Meeting,
  MeetingListItem,
  MeetingUpdate,
  TranscriptResponse,
  User,
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
const AUTH_REQUEST_TIMEOUT_MS = 6000;
const TOKEN_KEY = "meeting_agent_token";
const USER_KEY = "meeting_agent_user";
const SESSION_MODE_KEY = "meeting_agent_session_mode";

export type SessionMode = "demo" | "signed-in";

let unauthorizedHandler: (() => void) | null = null;

export function setUnauthorizedHandler(handler: (() => void) | null) {
  unauthorizedHandler = handler;
}

export function getAuthToken(): string {
  return localStorage.getItem(TOKEN_KEY) ?? "";
}

export function getStoredUser(): User | null {
  const stored = localStorage.getItem(USER_KEY);
  if (!stored) return null;
  try {
    return JSON.parse(stored) as User;
  } catch {
    return null;
  }
}

export function getStoredSessionMode(): SessionMode | null {
  const stored = localStorage.getItem(SESSION_MODE_KEY);
  return stored === "demo" || stored === "signed-in" ? stored : null;
}

export function storeAuth(auth: AuthResponse, mode: SessionMode) {
  localStorage.setItem(TOKEN_KEY, auth.access_token);
  localStorage.setItem(USER_KEY, JSON.stringify(auth.user));
  localStorage.setItem(SESSION_MODE_KEY, mode);
}

export function clearAuth() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
  localStorage.removeItem(SESSION_MODE_KEY);
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

export function analyzeMeeting(payload: AnalyzeRequest): Promise<Meeting> {
  return request<Meeting>("/api/meetings/analyze", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function transcribeMeetingAudio(file: File): Promise<TranscriptResponse> {
  const form = new FormData();
  form.append("file", file);

  const response = await fetch(`${API_BASE}/api/meetings/transcribe`, {
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
