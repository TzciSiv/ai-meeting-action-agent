export type ActionStatus = "Open" | "In Progress" | "Done";

export interface ActionItem {
  id: number;
  meeting_id: number;
  task: string;
  owner: string;
  deadline: string;
  evidence: string;
  status: ActionStatus;
  source_run_id: string;
  created_at: string;
  updated_at: string;
}

export interface FollowUpSource {
  chunk_index: number;
  content: string;
  rank: number;
  score: number;
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
  follow_up_sources: FollowUpSource[];
  run_id?: string | null;
  ai_run_ids: string[];
  prompt_version: string;
  model: string;
  generation_latency_ms: number;
  embedding_model: string;
  chunking_version: string;
  embedding_status: string;
  last_embedded_at?: string | null;
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

export interface IngestResponse {
  job_id: string;
  status: string;
  meeting_id?: number | null;
  current_step: string;
  file_size_bytes: number;
}

export interface IngestionJob {
  id: number;
  job_id: string;
  user_id?: number | null;
  meeting_id?: number | null;
  source_type: string;
  filename: string;
  file_size_bytes: number;
  status: string;
  current_step: string;
  error_message: string;
  created_at: string;
  updated_at: string;
}

export interface PipelineEventEnvelope {
  event_id: string;
  event_type: string;
  event_version: string;
  occurred_at: string;
  actor_user_id?: number | null;
  correlation_id: string;
  job_id?: string | null;
  meeting_id?: number | null;
  resource_type: string;
  resource_id?: string | null;
  payload: Record<string, unknown>;
}

export interface JobEventMessage {
  job: IngestionJob;
  event?: PipelineEventEnvelope;
}

export type TranscriptionJobStatus = "running" | "completed" | "failed";
export type AnalysisJobStatus = "running" | "completed" | "failed";

export interface TranscriptionJob {
  jobId?: string;
  fileName: string;
  fileSize?: number;
  status: TranscriptionJobStatus;
  currentStep?: string;
  startedAt: string;
  completedAt?: string;
  transcriptLength?: number;
  error?: string;
}

export interface ActiveAnalysisJob {
  jobId: string;
  status: AnalysisJobStatus;
  currentStep: string;
  filename: string;
  sourceType: string;
  startedAt: string;
  completedAt?: string;
  meetingId?: number | null;
  error?: string;
}

export interface User {
  id: number;
  email: string;
  role: string;
  created_at: string;
}

export interface AuthResponse {
  access_token: string;
  token_type: "bearer";
  user: User;
}

export interface LatencyMetric {
  count: number;
  average_seconds: number;
  max_seconds: number;
  latest_seconds: number;
}

export interface MetricsSnapshot {
  uptime_seconds: number;
  counters: Record<string, number>;
  latencies: Record<string, LatencyMetric>;
  sla_targets: {
    scope: string;
    analysis_average_seconds: number;
    analysis_max_seconds: number;
    error_rate_objective: string;
    health_endpoint: string;
  };
  integrations: {
    prometheus: {
      enabled: boolean;
      available: boolean;
      endpoint: string;
    };
    opentelemetry: {
      enabled: boolean;
      available: boolean;
      service_name: string;
      otlp_endpoint: string;
    };
  };
  models: {
    transcription: string;
    summary: string;
    embedding: string;
  };
}

export interface PromptGovernanceItem {
  id: number;
  prompt_id: string;
  version: string;
  task_type: string;
  purpose: string;
  model: string;
  temperature: number;
  template_hash: string;
  created_by?: number | null;
  created_at: string;
}

export interface AuditEvent {
  id: number;
  action: string;
  resource_type: string;
  resource_id: string;
  event_type: string;
  entity_type: string;
  entity_id: string;
  status: string;
  request_id: string;
  run_id?: string;
  metadata: Record<string, unknown>;
  ip_hash: string;
  user_agent_hash: string;
  created_at: string;
}

export interface AuditEventPage {
  items: AuditEvent[];
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
}

export interface AiRun {
  id: number;
  run_id: string;
  user_id?: number | null;
  meeting_id?: number | null;
  prompt_version_id?: number | null;
  prompt_version?: PromptGovernanceItem | null;
  model: string;
  retrieved_chunk_ids: string[];
  output_hash: string;
  latency_ms: number;
  input_tokens: number;
  output_tokens: number;
  cost_estimate: number;
  created_at: string;
}

export interface PipelineTopicMetric {
  topic: string;
  pending: number;
  published: number;
  failed: number;
  processed: number;
}

export interface WorkerStatus {
  id: number;
  worker_id: string;
  display_name: string;
  hostname: string;
  mode: string;
  status: string;
  current_topic: string;
  current_job_id: string;
  current_event_type: string;
  processed_count: number;
  failed_count: number;
  last_error: string;
  started_at: string;
  last_seen_at: string;
  seconds_since_seen: number;
}

export interface PipelineOperations {
  expected_worker_count: number;
  reporting_worker_count: number;
  missing_worker_count: number;
  stale_worker_count: number;
  job_counts: Record<string, number>;
  workers: WorkerStatus[];
  kafka_topics: PipelineTopicMetric[];
  failed_job_count: number;
  failed_jobs: IngestionJob[];
}
