# AI Governance

## Scope

This project treats meeting transcripts as sensitive enterprise records. Every generated output must be traceable to an authenticated user, meeting, prompt version, model configuration, AI run record, and audit event.

## Risk Framework Mapping

- NIST AI RMF: governed prompt registry, measurable eval checks, traceable AI runs, and incident-ready audit records.
- NIST Generative AI Profile: prompt-injection test fixtures, unsupported-claim eval metrics, and explicit `Not mentioned` behavior for unsupported follow-up answers.
- OWASP LLM Top 10: object authorization, prompt injection resilience, evidence grounding, output validation, rate limits, and sensitive logging controls.
- OWASP Web Top 10 2025: JWT auth, RBAC, object-level checks, upload limits, structured error handling, and dependency scanning.
- OpenAI production and safety practices: model/prompt versioning, no secret logging, bounded tool behavior, and clear evidence limits for follow-up answers.
- ISO/IEC 42001: documented governance process, auditability, and continuous evaluation.
- AWS Well-Architected ML Lens: operational metrics, cost/token tracking, deployment separation, CI checks, and reliability-oriented eval gates.

## AI Data Flow

1. User authenticates with JWT.
2. `POST /api/meetings/ingest` creates an `ingestion_jobs` record and a safe `meeting.uploaded` outbox event. Kafka payloads carry IDs, status, hashes, filenames, and metadata only; raw transcript text stays in Postgres.
3. The worker consumes `meeting.uploaded` as a router. Transcript text queues `analysis.requested`; audio and DOCX inputs queue `transcription.requested` first, then queue `analysis.requested` after transcript text is stored.
4. Prompt registry resolves the latest registered prompt versions before any production analysis.
5. Meeting analysis runs summary, action/risk extraction, retrieval, and grounded Q&A.
6. Each LLM call creates an `ai_runs` trace with prompt version, model, retrieved chunks, output hash, latency, tokens, and cost estimate.
7. Follow-up Q&A stores retrieved evidence snippets only when the answer is supported by retrieved meeting chunks.
8. The API streams job status to the frontend through SSE and returns generated meeting output when complete.

Reusable governance utilities support:

- prompt/RAG eval regression
- batch transcript import
- re-embedding scans after chunking/model changes

## Prompt Governance

Prompts are registered in `backend/prompts.py` and synchronized into `prompt_versions`. Production analysis uses the newest synchronized version for each prompt.

Prompt versions include:

- `prompt_id`
- `version`
- `task_type`
- `model`
- `temperature`
- `template_hash`
- `created_by`
- `created_at`

Prompt governance is currently read-only in the UI; prompt changes are made in code and then synchronized at startup.

## Hallucination Controls

- Follow-up answers use retrieved transcript chunks only.
- Missing or weak evidence returns `Not mentioned`.
- Action items require evidence text.
- General meeting summaries, decisions, risks, and actions do not show transcript citations because those matches were too noisy for users.
- Retrieved evidence remains available for follow-up Q&A because it directly explains the answer.

## Eval Thresholds

Local eval checks track:

- pass rate at least `0.85`
- citation coverage at least `0.90`
- unsupported claim rate at most `0.05`
- JSON validity rate equal to `1.0`

The offline command is:

```bash
python -m evals.run --json
```

## Audit Logging Policy

Audit events record metadata only:

- actor user id
- action
- resource type and id
- metadata JSON
- request id
- hashed IP
- hashed user agent
- timestamp

Audit events must not contain raw transcripts, secrets, JWTs, full prompts, or provider API keys.

Kafka events follow the same sensitive payload rule. Event envelopes include `event_id`, `event_type`, `correlation_id`, `job_id`, `meeting_id`, resource metadata, and sanitized payload fields.

## Incident Response

1. Identify affected `audit_events` and `ai_runs`.
2. Use output hashes and prompt versions to isolate the generation path.
3. Pause or retire the affected prompt version.
4. Execute local evaluation fixtures and add a regression case.
5. Notify affected users if transcript access, export, or deletion behavior was involved.
6. Ship a fixed prompt version after local checks pass.

## Known Limitations

- Local evals are deterministic guardrails, not a full human-graded eval suite.
- Token cost is estimated unless provider billing telemetry is connected.
- SQLite is not the production target; Postgres is required for this app.
- Meeting sharing is represented by `meeting_permissions`, but no self-service sharing UI is included yet.
