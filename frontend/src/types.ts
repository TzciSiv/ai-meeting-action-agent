export type ActionStatus = "Open" | "In Progress" | "Done";

export interface ActionItem {
  id: number;
  meeting_id: number;
  task: string;
  owner: string;
  deadline: string;
  evidence: string;
  status: ActionStatus;
  created_at: string;
  updated_at: string;
}

export interface Meeting {
  id: number;
  title: string;
  transcript: string;
  summary_markdown: string;
  summary: Record<string, unknown>;
  decisions: string[];
  risks: string[];
  follow_up_question: string;
  follow_up_answer: string;
  created_at: string;
  updated_at: string;
  actions: ActionItem[];
}

export interface MeetingListItem {
  id: number;
  title: string;
  follow_up_question: string;
  follow_up_answer: string;
  created_at: string;
  updated_at: string;
  action_count: number;
  done_count: number;
}

export interface AnalyzeRequest {
  transcript: string;
  follow_up_question: string;
  title?: string;
  summary_engine: "gpt" | "local";
}

export interface MeetingUpdate {
  title?: string;
}

export interface ActionUpdate {
  task?: string;
  owner?: string;
  deadline?: string;
  evidence?: string;
  status?: ActionStatus;
}

export interface TranscriptResponse {
  transcript: string;
}

export type TranscriptionJobStatus = "running" | "completed" | "failed";

export interface TranscriptionJob {
  fileName: string;
  fileSize: number;
  status: TranscriptionJobStatus;
  startedAt: string;
  completedAt?: string;
  transcriptLength?: number;
  error?: string;
}

export interface User {
  id: number;
  email: string;
  created_at: string;
}

export interface AuthResponse {
  access_token: string;
  token_type: "bearer";
  user: User;
}
