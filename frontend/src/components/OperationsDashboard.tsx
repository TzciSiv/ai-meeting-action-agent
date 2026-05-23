import { type FormEvent, useEffect, useMemo, useState } from "react";

import {
  getAiRun,
  getOperationalMetrics,
  getPipelineOperations,
  getPromptGovernance,
  listAuditEvents,
} from "../api";
import type { AiRun, AuditEvent, MetricsSnapshot, PipelineOperations, PromptGovernanceItem } from "../types";

const AUDIT_PAGE_SIZE = 20;
type PageItem = number | "ellipsis-left" | "ellipsis-right";

function formatSeconds(value: number) {
  if (!Number.isFinite(value)) return "0.00s";
  if (value >= 60) return `${(value / 60).toFixed(1)}m`;
  return `${value.toFixed(value >= 10 ? 1 : 2)}s`;
}

function formatDate(value: string) {
  return new Date(value).toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function sortedEntries<T extends number | { average_seconds: number }>(items: Record<string, T>) {
  return Object.entries(items).sort(([, left], [, right]) => {
    const leftValue = typeof left === "number" ? left : left.average_seconds;
    const rightValue = typeof right === "number" ? right : right.average_seconds;
    return rightValue - leftValue;
  });
}

function statusLabel(ok: boolean) {
  return ok ? "Within target" : "Review needed";
}

function pageRange(start: number, end: number) {
  return Array.from({ length: end - start + 1 }, (_, index) => start + index);
}

function visiblePageItems(currentPage: number, totalPages: number): PageItem[] {
  if (totalPages <= 5) {
    return pageRange(1, totalPages);
  }

  if (currentPage <= 4) {
    return [...pageRange(1, 5), "ellipsis-right", totalPages];
  }

  if (currentPage >= totalPages - 3) {
    return [1, "ellipsis-left", ...pageRange(totalPages - 4, totalPages)];
  }

  return [1, "ellipsis-left", currentPage - 1, currentPage, currentPage + 1, "ellipsis-right", totalPages];
}

function workerSeenLabel(seconds: number) {
  if (seconds < 10) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ago`;
}

function workerStatusText(status: string) {
  const labels: Record<string, string> = {
    idle: "Idle",
    processing: "Processing",
    starting: "Starting",
    stale: "Not reporting",
    missing: "Not reporting",
    error: "Error",
  };
  return labels[status] ?? status;
}

function jobCountLabel(status: string) {
  const labels: Record<string, string> = {
    completed: "Completed",
    failed: "Failed",
    processing: "Processing",
    queued: "Queued",
    running: "Running",
  };
  return `${labels[status] ?? status} jobs`;
}

function errorMessage(reason: unknown, fallback: string) {
  return reason instanceof Error ? reason.message : fallback;
}

export default function OperationsDashboard() {
  const [metrics, setMetrics] = useState<MetricsSnapshot | null>(null);
  const [pipeline, setPipeline] = useState<PipelineOperations | null>(null);
  const [prompts, setPrompts] = useState<PromptGovernanceItem[]>([]);
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [auditPage, setAuditPage] = useState(1);
  const [auditTotal, setAuditTotal] = useState(0);
  const [auditTotalPages, setAuditTotalPages] = useState(1);
  const [auditLoading, setAuditLoading] = useState(false);
  const [auditJumpPage, setAuditJumpPage] = useState("1");
  const [runId, setRunId] = useState("");
  const [aiRun, setAiRun] = useState<AiRun | null>(null);
  const [runLookupError, setRunLookupError] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const analysisLatency = metrics?.latencies["analysis.graph.run"];
  const averageOk = !analysisLatency || analysisLatency.average_seconds <= metrics.sla_targets.analysis_average_seconds;
  const maxOk = !analysisLatency || analysisLatency.max_seconds <= metrics.sla_targets.analysis_max_seconds;

  const topCounters = useMemo(() => sortedEntries(metrics?.counters ?? {}).slice(0, 8), [metrics]);
  const topLatencies = useMemo(() => sortedEntries(metrics?.latencies ?? {}).slice(0, 8), [metrics]);
  const auditPageItems = useMemo(() => visiblePageItems(auditPage, auditTotalPages), [auditPage, auditTotalPages]);

  function applyAuditPage(payload: Awaited<ReturnType<typeof listAuditEvents>>) {
    setAuditEvents(payload.items);
    setAuditPage(payload.page);
    setAuditTotal(payload.total);
    setAuditTotalPages(payload.total_pages);
    setAuditJumpPage(String(payload.page));
  }

  async function fetchResolvedAuditPage(page: number) {
    const payload = await listAuditEvents(page, AUDIT_PAGE_SIZE);
    if (payload.total > 0 && payload.items.length === 0 && page > payload.total_pages) {
      return listAuditEvents(payload.total_pages, AUDIT_PAGE_SIZE);
    }
    return payload;
  }

  async function loadAuditPage(page: number) {
    setAuditLoading(true);
    setError("");
    try {
      applyAuditPage(await fetchResolvedAuditPage(page));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not load audit events.");
    } finally {
      setAuditLoading(false);
    }
  }

  function normalizedAuditJumpPage(value: string) {
    const parsed = Number.parseInt(value, 10);
    if (!Number.isFinite(parsed)) return auditPage;
    return Math.min(Math.max(parsed, 1), auditTotalPages);
  }

  function handleAuditJumpSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (auditLoading) return;
    const nextPage = normalizedAuditJumpPage(auditJumpPage);
    setAuditJumpPage(String(nextPage));
    if (nextPage !== auditPage) {
      void loadAuditPage(nextPage);
    }
  }

  async function loadOperations(page = auditPage) {
    setLoading(true);
    setError("");
    try {
      const [metricsResult, promptsResult, auditResult, pipelineResult] = await Promise.allSettled([
        getOperationalMetrics(),
        getPromptGovernance(),
        fetchResolvedAuditPage(page),
        getPipelineOperations(),
      ]);

      let nextError = "";
      if (metricsResult.status === "fulfilled") {
        setMetrics(metricsResult.value);
      } else {
        nextError = errorMessage(metricsResult.reason, "Could not load operational metrics.");
      }

      setPrompts(promptsResult.status === "fulfilled" ? promptsResult.value : []);

      if (auditResult.status === "fulfilled") {
        applyAuditPage(auditResult.value);
      } else {
        nextError ||= errorMessage(auditResult.reason, "Could not load audit events.");
      }

      setPipeline(pipelineResult.status === "fulfilled" ? pipelineResult.value : null);
      setError(nextError);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not load operations data.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadOperations();
  }, []);

  async function handleLookupRun() {
    const normalizedRunId = runId.trim();
    setRunLookupError("");
    setAiRun(null);
    if (!normalizedRunId) {
      setRunLookupError("Enter a Run ID.");
      return;
    }
    try {
      setAiRun(await getAiRun(normalizedRunId));
    } catch (caught) {
      setRunLookupError(caught instanceof Error ? caught.message : "Run ID invalid or not found.");
    }
  }

  return (
    <section className="operations-page">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Production operations</p>
          <h2>Monitoring and AI governance</h2>
        </div>
        <button className="button secondary" type="button" onClick={() => void loadOperations()} disabled={loading}>
          {loading ? "Refreshing..." : "Refresh"}
        </button>
      </div>

      {error && <div className="notice error">{error}</div>}

      {metrics && (
        <>
          <div className="metric-row operations-metrics">
            <div className="metric">
              <span>Uptime</span>
              <strong>{formatSeconds(metrics.uptime_seconds)}</strong>
            </div>
            <div className={`metric ${averageOk ? "ok" : "warn"}`}>
              <span>Analysis average</span>
              <strong>{formatSeconds(analysisLatency?.average_seconds ?? 0)}</strong>
              <small>{statusLabel(averageOk)}</small>
            </div>
            <div className={`metric ${maxOk ? "ok" : "warn"}`}>
              <span>Analysis max</span>
              <strong>{formatSeconds(analysisLatency?.max_seconds ?? 0)}</strong>
              <small>{statusLabel(maxOk)}</small>
            </div>
          </div>

          <div className="ops-grid ops-grid-start">
            <section className="panel ops-panel">
              <h3>Telemetry</h3>
              <div className="ops-status-grid">
                <div>
                  <span>Prometheus</span>
                  <strong>{metrics.integrations.prometheus.enabled ? "Enabled" : "Disabled"}</strong>
                  <small>{metrics.integrations.prometheus.endpoint}</small>
                </div>
                <div>
                  <span>OpenTelemetry</span>
                  <strong>{metrics.integrations.opentelemetry.enabled ? "Enabled" : "Disabled"}</strong>
                  <small>{metrics.integrations.opentelemetry.service_name}</small>
                </div>
              </div>
            </section>

            <section className="panel ops-panel">
              <h3>Model Configuration</h3>
              <div className="ops-status-grid">
                <div>
                  <span>Transcription</span>
                  <strong>{metrics.models.transcription}</strong>
                </div>
                <div>
                  <span>Summary</span>
                  <strong>{metrics.models.summary}</strong>
                </div>
                <div>
                  <span>Embedding</span>
                  <strong>{metrics.models.embedding}</strong>
                </div>
              </div>
            </section>
          </div>

          <section className="panel ops-panel">
            <h3>SLA Targets</h3>
            <div className="ops-status-grid">
              <div>
                <span>Average</span>
                <strong>{formatSeconds(metrics.sla_targets.analysis_average_seconds)}</strong>
              </div>
              <div>
                <span>Max</span>
                <strong>{formatSeconds(metrics.sla_targets.analysis_max_seconds)}</strong>
              </div>
              <div>
                <span>Error rate</span>
                <strong>{metrics.sla_targets.error_rate_objective}</strong>
              </div>
            </div>
          </section>

          <div className="ops-grid ops-grid-start">
            <section className="panel ops-panel">
              <h3>Top Counters</h3>
              <div className="ops-table">
                {topCounters.map(([name, value]) => (
                  <div key={name}>
                    <span>{name}</span>
                    <strong>{value}</strong>
                  </div>
                ))}
              </div>
            </section>

            <section className="panel ops-panel">
              <h3>Slowest Operations</h3>
              <div className="ops-table">
                {topLatencies.map(([name, value]) => (
                  <div key={name}>
                    <span>{name}</span>
                    <strong>{formatSeconds(value.average_seconds)}</strong>
                  </div>
                ))}
              </div>
            </section>
          </div>
        </>
      )}

      {pipeline && (
        <>
          <section className="panel ops-panel">
            <div className="ops-title-row audit-title-row">
              <h3>System Async Pipeline</h3>
              <span>
                {pipeline.reporting_worker_count} of {pipeline.expected_worker_count} workers reporting
              </span>
            </div>
            <p className="ops-context-note">
              Database-wide queue status for all accounts, including worker heartbeats, current jobs, and failed-job details.
            </p>
            {(pipeline.missing_worker_count > 0 || pipeline.stale_worker_count > 0) && (
              <p className="ops-context-note">
                {pipeline.missing_worker_count > 0
                  ? `${pipeline.missing_worker_count} worker${pipeline.missing_worker_count === 1 ? "" : "s"} have not sent a heartbeat yet. `
                  : ""}
                {pipeline.stale_worker_count > 0
                  ? `${pipeline.stale_worker_count} worker${pipeline.stale_worker_count === 1 ? "" : "s"} have stale heartbeat data.`
                  : ""}
              </p>
            )}
            <div className="worker-grid">
              {(pipeline.workers ?? []).map((worker) => (
                <article className={`worker-card status-${worker.status}`} key={worker.worker_id}>
                  <div className="worker-card-title">
                    <strong>{worker.display_name || worker.worker_id}</strong>
                    <span>{workerStatusText(worker.status)}</span>
                  </div>
                  {worker.status === "missing" ? (
                    <small>This worker container has not sent a recent heartbeat.</small>
                  ) : (
                    <>
                      <small>
                        {worker.mode} | last seen {workerSeenLabel(worker.seconds_since_seen)}
                      </small>
                      {worker.current_topic && (
                        <small>
                          {worker.current_topic}
                          {worker.current_event_type ? ` | ${worker.current_event_type}` : ""}
                        </small>
                      )}
                      {worker.current_job_id && <code>job {worker.current_job_id.slice(0, 8)}</code>}
                      <small>
                        processed {worker.processed_count} | failed {worker.failed_count}
                      </small>
                      {worker.last_error && <small className="worker-error">{worker.last_error}</small>}
                    </>
                  )}
                </article>
              ))}
            </div>
            <div className="ops-status-grid">
              {Object.entries(pipeline.job_counts).map(([status, count]) => (
                <div key={status}>
                  <span>{jobCountLabel(status)}</span>
                  <strong>{count}</strong>
                </div>
              ))}
            </div>
          </section>

          <div className="ops-grid ops-grid-start">
            <section className="panel ops-panel">
              <h3>Kafka Events</h3>
              <div className="ops-table">
                {pipeline.kafka_topics.length === 0 ? (
                  <p className="muted">No events queued yet.</p>
                ) : (
                  pipeline.kafka_topics.map((topic) => (
                    <div key={topic.topic}>
                      <span>{topic.topic}</span>
                      <strong>{topic.published + topic.processed}</strong>
                      <small>
                        pending {topic.pending} | failed {topic.failed}
                      </small>
                    </div>
                  ))
                )}
              </div>
            </section>

            <section className={`panel ops-panel failed-jobs-panel ${pipeline.failed_job_count === 0 ? "is-empty" : ""}`}>
              <div className="ops-title-row audit-title-row">
                <h3>Failed Jobs</h3>
                <span>{pipeline.failed_job_count} failed</span>
              </div>
              {pipeline.failed_job_count === 0 ? (
                <div className="ops-empty-state">
                  <div>
                    <strong>All clear</strong>
                    <span>No failed jobs in recent pipeline runs.</span>
                  </div>
                </div>
              ) : (
                <div className="ops-table">
                  {pipeline.failed_jobs.map((job) => (
                    <div key={job.job_id}>
                      <span>{job.filename || job.source_type}</span>
                      <strong>{job.current_step}</strong>
                      <small>{job.error_message || formatDate(job.updated_at)}</small>
                    </div>
                  ))}
                </div>
              )}
            </section>
          </div>
        </>
      )}

      <section className="panel ops-panel">
        <div className="ops-title-row">
          <h3>Prompt Governance</h3>
          <span
            className="info-dot"
            tabIndex={0}
            aria-label="Use this to see exactly which prompt versions the app is using for summaries, follow-up answers, and action extraction. When output quality changes, compare these versions and hashes with recent audit events before updating prompts."
          >
            i
          </span>
        </div>
        <div className="prompt-grid">
          {prompts.map((prompt) => (
            <article key={prompt.id}>
              <div>
                <span>{prompt.task_type}</span>
                <strong>{prompt.prompt_id}</strong>
              </div>
              <p>
                {prompt.model} at temperature {prompt.temperature}
              </p>
              <small>Version {prompt.version}</small>
              <code>{prompt.template_hash.slice(0, 16)}</code>
            </article>
          ))}
        </div>
      </section>

      <section className="panel ops-panel">
        <h3>AI Run Trace Viewer</h3>
        <div className="run-lookup">
          <input value={runId} onChange={(event) => setRunId(event.target.value)} placeholder="Paste run_id" />
          <button className="button secondary" type="button" onClick={() => void handleLookupRun()}>
            Load run
          </button>
        </div>
        {runLookupError && <div className="notice error run-lookup-error">{runLookupError}</div>}
        {aiRun && (
          <div className="ops-status-grid run-trace-grid">
            <div>
              <span>Run</span>
              <strong>{aiRun.run_id}</strong>
            </div>
            <div>
              <span>Prompt</span>
              <strong>{aiRun.prompt_version?.prompt_id ?? aiRun.prompt_version_id ?? "Unknown"}</strong>
            </div>
            <div>
              <span>Retrieved chunks</span>
              <strong>{aiRun.retrieved_chunk_ids.length}</strong>
            </div>
            <div>
              <span>Tokens</span>
              <strong>{aiRun.input_tokens + aiRun.output_tokens}</strong>
            </div>
            <div>
              <span>Output hash</span>
              <strong>{aiRun.output_hash.slice(0, 16)}</strong>
            </div>
          </div>
        )}
      </section>

      <section className="panel ops-panel">
        <div className="ops-title-row audit-title-row">
          <h3>Recent Audit Events</h3>
          <span>
            Page {auditPage} of {auditTotalPages} | {auditTotal} events
          </span>
        </div>
        <div className="audit-list">
          {auditLoading ? (
            <p className="muted">Loading audit events...</p>
          ) : auditEvents.length === 0 ? (
            <p className="muted">No audit events yet.</p>
          ) : (
            auditEvents.map((event) => (
              <article key={event.id}>
                <div>
                  <strong>{event.action}</strong>
                  <span>{formatDate(event.created_at)}</span>
                </div>
                <small>
                  {event.resource_type || "system"} {event.resource_id ? `#${event.resource_id}` : ""} - {event.status}
                </small>
                {event.run_id && <code>run id #{event.run_id}</code>}
                {event.request_id && <code>request_id #{event.request_id}</code>}
                {(event.ip_hash || event.user_agent_hash) && (
                  <small>
                    ip {event.ip_hash.slice(0, 10) || "none"} | ua {event.user_agent_hash.slice(0, 10) || "none"}
                  </small>
                )}
              </article>
            ))
          )}
        </div>
        {auditTotalPages > 1 && (
          <nav className="pagination-controls" aria-label="Audit event pages">
            {auditPage > 1 && (
              <button
                className="page-arrow"
                type="button"
                disabled={auditLoading}
                aria-label="Previous audit page"
                onClick={() => void loadAuditPage(auditPage - 1)}
              >
                &lsaquo;
              </button>
            )}
            <div className="page-number-row">
              {auditPageItems.map((item) =>
                typeof item === "number" ? (
                  <button
                    key={item}
                    className={`page-button ${item === auditPage ? "active" : ""}`}
                    type="button"
                    disabled={auditLoading || item === auditPage}
                    aria-current={item === auditPage ? "page" : undefined}
                    onClick={() => void loadAuditPage(item)}
                  >
                    {item}
                  </button>
                ) : (
                  <span className="page-ellipsis" key={item}>
                    ...
                  </span>
                ),
              )}
            </div>
            {auditPage < auditTotalPages && (
              <button
                className="page-arrow"
                type="button"
                disabled={auditLoading}
                aria-label="Next audit page"
                onClick={() => void loadAuditPage(auditPage + 1)}
              >
                &rsaquo;
              </button>
            )}
            <form className="page-jump-form" onSubmit={handleAuditJumpSubmit}>
              <label htmlFor="audit-page-jump">Go to page</label>
              <input
                id="audit-page-jump"
                type="number"
                inputMode="numeric"
                min={1}
                max={auditTotalPages}
                value={auditJumpPage}
                disabled={auditLoading}
                onChange={(event) => setAuditJumpPage(event.target.value)}
              />
              <button className="page-jump-button" type="submit" disabled={auditLoading}>
                Go
              </button>
            </form>
          </nav>
        )}
      </section>
    </section>
  );
}
