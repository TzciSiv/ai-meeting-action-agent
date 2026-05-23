# ai-meeting-action-agent

A full-stack meeting assistant built with React, TypeScript, FastAPI, Postgres/pgvector, JWT auth, and OpenAI. It turns a meeting transcript into private meeting records, action items, RAG-backed follow-up answers, and downloadable Word reports.

## Project Overview

AI Meeting Action Agent is designed for teams that need a cleaner way to turn messy meeting conversations into useful follow-up work. Instead of stopping at a plain summary, the app stores each meeting in a private workspace, extracts decisions and risks, builds a task board from the transcript, and lets users keep managing those action items after the meeting ends.

The project demonstrates a production-style AI workflow rather than a single prompt call. It combines audio transcription, transcript cleanup, structured LLM analysis, vector search, authenticated persistence, editable action tracking, and `.docx` exports. The result is a practical meeting operations tool: users can upload or paste meeting content, run the agent, review the outcome, ask a grounded follow-up question, and export a report they can share.

## What Problem It Solves

Meeting notes often leave teams with three problems: important decisions get buried in long transcripts, owners and deadlines are easy to miss, and follow-up questions require rereading the whole meeting. This app addresses those problems by creating a searchable, saved meeting record with:

- A readable transcript and structured summary.
- Clear decisions and risks detected from the meeting.
- Action items with task, owner, deadline, evidence, and status.
- Follow-up answers grounded in retrieved transcript snippets.
- A persistent action board that can be updated after the meeting.
- Word exports for transcripts and full meeting reports.

## User Workflow

1. Start in demo mode or sign in to a private workspace.
2. Paste a transcript, import a transcript document, or transcribe meeting audio.
3. Add an optional follow-up question for the agent to answer from the meeting.
4. Run the analysis workflow.
5. Review the summary, decisions, risks, retrieved evidence, and action board.
6. Reopen saved meetings later from history.
7. Rename meetings, delete old meetings, and update action item status.
8. Export either the transcript or a complete meeting report as a Word document.

## Application Screens

- **Analyze Meeting:** Main workspace for entering a transcript, importing content, asking a follow-up question, and running the agent.
- **Transcription Job:** Shows the current transcript generated from uploaded audio and lets the user return to analysis.
- **Meeting History:** Lists saved meetings with action counts, completion counts, rename controls, and delete controls.
- **Action Follow-Up:** Lets users reopen a meeting and continue updating tasks after the original analysis.
- **Operations:** Shows backend metrics, SLA status, telemetry integrations, prompt governance, and audit events.
- **Authentication:** Supports registration, login, logout, and a demo account for quick exploration.

## How The Agent Works

The backend coordinates several smaller steps so the output is easier to trust and manage:

- Normalizes transcript spacing before analysis.
- Queues a production-style async pipeline that creates a job, writes safe Kafka/outbox events, and runs the LangGraph workflow in the worker.
- Uses LangChain structured outputs for meeting summary content, action items, risks, and grounded answers.
- Splits the transcript into overlapping LangChain text chunks for retrieval.
- Embeds those chunks with `text-embedding-3-small`.
- Stores chunk embeddings in LangChain PGVector tables backed by Postgres.
- Retrieves the most relevant transcript chunks for a follow-up question.
- Generates a grounded answer using only the retrieved meeting evidence.
- Saves the meeting, generated fields, sources, and action items to the database.

## Architecture At A Glance

The app is split into a React frontend, a FastAPI backend, and a Postgres database with pgvector enabled.

- The frontend provides the meeting workspace, authentication screens, transcript input, action board, history view, and export buttons.
- The backend exposes authenticated REST endpoints for transcription, async meeting ingestion, saved meetings, actions, and exports.
- Postgres stores users, meetings, action items, and LangChain PGVector collections.
- pgvector stores embeddings so follow-up answers can be based on relevant transcript evidence.
- OpenAI APIs handle transcription, while LangChain/LangGraph coordinate GPT analysis, embeddings, retrieval, and follow-up answers.
- Docker Compose runs the frontend, backend, database, and test profile together.

## Main Features

- Queue durable meeting-audio transcription jobs with `gpt-4o-mini-transcribe` and format the output into a readable transcript.
- Import existing `.docx` transcript documents into the analysis workflow.
- Queue transcript analysis through the async worker pipeline to generate summaries, risks, decisions, and action items.
- Split the current meeting transcript into overlapping LangChain chunks, embed them with `text-embedding-3-small`, and store them in PGVector.
- Answer follow-up questions from retrieved current-meeting evidence snippets.
- Extract action items with the LangGraph insights node for cleaner task tracking.
- Save meetings, transcripts, summaries, answers, evidence snippets, and action boards to Postgres.
- Reopen saved meetings from history and continue managing their action items.
- Add, edit, complete, and delete action items after the meeting.
- Export transcripts and full meeting reports as Word documents.

## Data Model

The database is intentionally small and focused:

- `users` stores account identity and hashed passwords.
- `meetings` stores transcript text, summary output, decisions, risks, follow-up answers, and source snippets.
- `action_items` stores task follow-up details connected to a meeting.
- `audit_events` stores safe traceability records for important user actions.
- LangChain PGVector tables store chunk text, metadata, and vector embeddings for retrieval.

This keeps meeting history, generated AI output, and task follow-up in one place while still separating each user's workspace through authenticated API calls.

## Implementation Highlights

- JWT authentication protects meeting and action endpoints.
- Logged-out users can inspect the sample input, while running jobs and saved-work actions require sign-in.
- The worker saves analysis results when the async pipeline completes so users can return later.
- Action items remain editable after generation, which makes the app useful beyond the first AI response.
- Follow-up answers include evidence snippets so users can inspect where the answer came from.
- Word exports reflect the current meeting state, including updated action statuses.
- Structured backend logs, Prometheus-compatible metrics, request IDs, and OpenTelemetry spans track request counts, graph runs, failures, exports, and latency.
- Audit events capture safe traceability for authentication, analysis, exports, deletes, and action changes.
- Prompt templates are versioned with documented safety rules and eval coverage for grounded outputs.
- Backend tests cover authentication, persistence, action management, exports, transcript import, graph nodes, and LLM transcription behavior.

## Operational Readiness

This project includes production-style AI operations controls:

- Docker Compose provides the deployment path for backend, worker, frontend, Postgres/pgvector, and Kafka.
- `GET /api/health` reports backend readiness.
- `GET /api/metrics` reports JSON counters, latency summaries, uptime, model configuration, SLA-style objectives, and telemetry integration status.
- `GET /metrics` returns Prometheus-compatible scrape output.
- Every backend response includes an `X-Request-ID` header for cross-log traceability.
- Structured backend logs record operational events without raw transcripts, retrieved source text, JWTs, passwords, API keys, or secrets.
- OpenTelemetry spans can be exported through OTLP when `OTEL_EXPORTER_OTLP_ENDPOINT` is configured.
- LangGraph node timing tracks latency across analysis, structured model calls, chunk storage, retrieval, and grounded follow-up answering.
- The Operations tab surfaces SLA status, model configuration, counters, slow operations, prompt versions, and recent audit events.
- Prompt governance lives in `backend/prompts.py`, where prompts have names, versions, schemas, purposes, and safety rules.
- Eval-style tests check hallucination controls such as evidence-backed actions, source-grounded answers, and `Not mentioned` for unsupported answers.
- `docs/ai-governance.md` documents security, prompt governance, eval expectations, hallucination mitigation, auditability, and governance workflows.

## Tech Stack

- **Frontend:** React, TypeScript, Vite, CSS
- **Backend:** FastAPI, Python, Pydantic
- **Database:** Postgres, pgvector, SQLAlchemy
- **Authentication:** JWT bearer tokens, password hashing
- **AI:** LangChain, LangGraph, OpenAI Transcription API, OpenAI GPT API, OpenAI Embeddings API
- **Observability:** JSON logs, Prometheus metrics, OpenTelemetry tracing, request IDs, audit events
- **Exports:** python-docx for Word transcript and report downloads
- **Testing:** unittest, FastAPI TestClient

## Project Structure

- `backend/api.py` - FastAPI app and REST routes.
- `backend/auth.py` - password hashing, JWT creation, and token validation.
- `backend/services.py` - meeting persistence, governed analysis persistence, action CRUD, and export orchestration.
- `backend/pipeline.py` - durable ingestion jobs, async worker steps, maintenance helpers, and pipeline status summaries.
- `backend/events.py` - safe Kafka event envelopes, outbox records, and publishing helpers.
- `backend/worker.py` - Kafka/outbox worker process for async transcription, embedding, and analysis.
- `backend/analysis_graph.py` - LangGraph workflow, LangChain structured outputs, chunking, PGVector storage, retrieval, and follow-up answers.
- `backend/governance.py` - prompt synchronization, meeting access checks, AI run traces, and AI budget helpers.
- `backend/prompts.py` - versioned prompt registry with safety rules and expected schemas.
- `backend/observability.py` - structured logging, Prometheus metrics, request IDs, tracing hooks, latency timing, and SLA objectives.
- `backend/models.py` - SQLAlchemy users, meetings, actions, prompt versions, AI runs, audits, jobs, worker heartbeats, and outbox tables.
- `backend/schemas.py` - API request and response schemas.
- `backend/exports.py` - `.docx` transcript and full-report builders.
- `backend/llm.py` - audio transcription and transcript-formatting helpers.
- `backend/transcript_import.py` - `.docx` transcript import helper.
- `docs/ai-governance.md` - canonical AI governance, eval, hallucination mitigation, and audit documentation.
- `docs/security.md` - JWT/RBAC, authorization, secrets, logging, Kafka payload, rate-limit, and dependency-scan policy.
- `frontend/src/` - React + TypeScript app.
- `frontend/src/components/` - meeting form, history, summary, action board, operations dashboard, exports, and authentication UI.
- `evals/` - offline governance fixtures and eval runner.
- `migrations/` - Alembic migrations for governance and async pipeline tables.
- `tests/` - backend, pipeline, governance, LangGraph analysis, transcript import, docx import, and LLM tests.

## Backend Workflow Diagram

```mermaid
flowchart TD
  request["Frontend REST request"]

  api["api.py<br/>FastAPI routes"]
  schemas["schemas.py<br/>Request and response shapes"]
  services["services.py<br/>Main workflow coordinator"]

  auth["auth.py<br/>Login, demo user, JWT checks"]
  database["database.py<br/>Database connection"]
  models["models.py<br/>User, Meeting, ActionItem tables"]
  postgres["Postgres + pgvector<br/>meeting_agent database"]

  graph["analysis_graph.py<br/>LangGraph workflow"]
  prompts["prompts.py<br/>Prompt registry + safety rules"]
  observability["observability.py<br/>Logs + metrics + traces"]
  audit["AuditEvent<br/>Traceability records"]
  langchain["LangChain<br/>Structured output + PGVector"]
  llm["llm.py<br/>Audio transcription + formatting"]
  exports["exports.py<br/>Word document builders"]

  openai["OpenAI API<br/>gpt-4o-mini-transcribe<br/>GPT analysis/answers<br/>text-embedding-3-small"]
  docx["Downloadable .docx files"]

  request --> api
  api --> schemas
  api --> auth
  auth --> database
  database --> models
  models --> postgres

  api --> services
  api --> observability
  api --> audit
  services --> graph
  services --> llm
  services --> database

  graph --> prompts
  graph --> observability
  graph --> langchain
  langchain --> postgres
  langchain --> openai
  llm --> openai

  api --> exports
  services --> exports
  exports --> docx
```

## Docker Setup

Install Docker Desktop first. Docker Compose reads your local `.env` file for secrets such as `OPENAI_API_KEY`, while service database URLs are set in `docker-compose.yml`.

Create a `.env` file from `.env.example`, then set `OPENAI_API_KEY`.

```bash
docker compose up --build
```

The backend applies the checked-in Alembic migrations during startup, so existing local Postgres volumes are brought up to the current schema automatically.

Open:

- Frontend: `http://localhost:5173`
- Backend health: `http://localhost:8000/api/health`
- Backend JSON metrics: `http://localhost:8000/api/metrics`
- Prometheus metrics: `http://localhost:8000/metrics`
Compose also starts Apache Kafka and three backend worker consumers. New meeting uploads use the async ingestion path:

```text
upload -> meeting.uploaded router -> transcription.requested if needed -> analysis.requested -> completion event -> SSE dashboard update
```

The default Kafka topic partition count is `3`, so the three worker consumers can process up to three partition-assigned jobs in parallel.

Run backend tests in Docker:

```bash
docker compose --profile test run --rm backend-test
```

Run static checks in Docker:

```bash
docker compose run --rm backend sh -c "python -m py_compile backend/*.py"
docker compose run --rm frontend npm run build
```

## Local Setup

Docker is the recommended path because the backend requires Postgres + pgvector. For local development, start Postgres first:

```bash
docker compose up -d postgres kafka
```

Install backend dependencies:

```bash
pip install -r requirements.txt
```

Install frontend dependencies:

```bash
cd frontend
npm install
```

Start the backend API:

```bash
python -m uvicorn backend.api:app --reload --port 8000
```

Start the async worker in a second terminal:

```bash
python -m backend.worker
```

Start the frontend:

```bash
cd frontend
npm run dev
```

Open the Vite URL shown in the terminal, usually `http://127.0.0.1:5173`.

## Environment

Create a `.env` file from `.env.example` and set:

```bash
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_TRANSCRIBE_MODEL=gpt-4o-mini-transcribe
OPENAI_SUMMARY_MODEL=gpt-5-mini
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
OPENAI_TIMEOUT_SECONDS=120
LANGCHAIN_PGVECTOR_COLLECTION=meeting_transcript_chunks
APP_LOG_LEVEL=INFO
PROMETHEUS_METRICS_ENABLED=true
OTEL_TRACES_ENABLED=true
OTEL_SERVICE_NAME=ai-meeting-action-agent
OTEL_EXPORTER_OTLP_ENDPOINT=
SLA_ANALYSIS_AVERAGE_SECONDS=30
SLA_ANALYSIS_MAX_SECONDS=120
SLA_ERROR_RATE_OBJECTIVE=below 5% in local/demo runs
DATABASE_URL=postgresql+psycopg://meeting_agent:meeting_agent@localhost:5432/meeting_agent
JWT_SECRET_KEY=change_this_to_a_long_random_secret
JWT_EXPIRE_MINUTES=10080
KAFKA_BOOTSTRAP_SERVERS=localhost:9092
KAFKA_ENABLED=true
```

Docker Compose overrides `DATABASE_URL` inside containers so the backend connects to the `postgres` service. Keep the localhost URL for running the backend directly on your machine.

The React app expects the API at `http://localhost:8000` by default. To change it, create `frontend/.env`:

```bash
VITE_API_BASE_URL=http://localhost:8000
```

## API Endpoints

- `POST /api/auth/register` - create a user and return a bearer token.
- `POST /api/auth/login` - authenticate a user and return a bearer token.
- `POST /api/auth/demo` - create or reuse the demo user and return a bearer token.
- `GET /api/auth/me` - return the current authenticated user.
- `GET /api/health` - return backend readiness.
- `GET /api/metrics` - return operational counters, latency summaries, model configuration, telemetry status, and SLA objectives.
- `GET /metrics` - return Prometheus-compatible metrics.
- `GET /api/governance/prompts` - return prompt names, versions, schemas, purposes, and safety rules.
- `GET /api/audit/events` - return recent audit events for the authenticated user.
- `POST /api/meetings/transcribe/jobs` - queue a durable audio transcription job.
- `GET /api/jobs/{job_id}/transcript` - return the finished transcript for a transcription job.
- `POST /api/meetings/import-transcript` - import transcript text from an uploaded `.docx` file.
- `POST /api/meetings/ingest` - queue async audio, DOCX, or transcript analysis and return a durable `job_id`.
- `GET /api/jobs/{job_id}` - return safe ingestion job status for authorized users.
- `GET /api/jobs/{job_id}/events` - stream safe job status and pipeline events with SSE.
- `GET /api/operations/pipeline` - return worker, Kafka/outbox, and failed-job status for admins.
- `GET /api/meetings` - list saved meetings.
- `GET /api/meetings/{id}` - get one meeting with summary, transcript, and actions.
- `PATCH /api/meetings/{id}` - rename a saved meeting.
- `DELETE /api/meetings/{id}` - delete a saved meeting and its related actions/chunks.
- `POST /api/meetings/{id}/actions` - add an action item to a meeting.
- `PATCH /api/actions/{id}` - edit action task, owner, deadline, evidence, or status.
- `DELETE /api/actions/{id}` - delete an action item.
- `GET /api/meetings/{id}/transcript` - download transcript as `.docx`.
- `GET /api/meetings/{id}/export` - download full meeting report as `.docx`.

## Test

```bash
docker compose --profile test run --rm backend-test
docker compose run --rm backend sh -c "python -m py_compile backend/*.py"
docker compose run --rm frontend npm run build
```

Backend tests use Postgres + pgvector and default to `postgresql+psycopg://meeting_agent:meeting_agent@postgres:5432/meeting_agent_test` inside Docker.

## Resume Title

**AI Meeting Action Agent**

## Resume Bullets

- Built a Dockerized AI meeting assistant with React, TypeScript, FastAPI, JWT auth, SQLAlchemy, Postgres/pgvector, LangChain, LangGraph, and OpenAI APIs.
- Designed REST endpoints for authentication, meeting analysis, saved meeting history, action-item CRUD, Word exports, health checks, Prometheus metrics, governance, and audit events.
- Implemented a LangGraph workflow that turns transcripts into summaries, decisions, risks, RAG follow-up answers, and structured action boards.
- Added current-meeting RAG with chunking, `text-embedding-3-small`, pgvector retrieval, visible evidence snippets, and `Not mentioned` fallback behavior.
- Added structured logging, Prometheus-compatible metrics, OpenTelemetry tracing hooks, request IDs, audit events, and SLA-style objectives for reliability-aware AI workflows.
- Added prompt governance with versioned prompt specs, structured LangChain outputs, and eval-style tests for hallucination mitigation.
- Built an operations dashboard for SLA status, counters, slow operations, prompt versions, and auditability.
- Documented AI governance controls for JWT access, per-user data isolation, secret-based config, safe logging, and prompt/eval review.
- Added persistent action follow-up so users can add, edit, delete, and mark tasks complete after the meeting.
- Generated `.docx` transcript and full-report downloads that reflect current database action statuses.
