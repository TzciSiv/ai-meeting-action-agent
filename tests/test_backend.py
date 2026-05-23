import unittest

import json
import os
import re

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker


DEFAULT_TEST_DATABASE_URL = "postgresql+psycopg://meeting_agent:meeting_agent@localhost:5432/meeting_agent_test"
os.environ["DATABASE_URL"] = os.getenv("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)
os.environ.setdefault("KAFKA_ENABLED", "false")
TEST_DATABASE_READY = False
TEST_DATABASE_ERROR: Exception | None = None

import backend.api as api_module
import backend.pipeline as pipeline_module
import backend.services as services_module
from backend.api import app
from backend.auth import DEMO_EMAIL, DEMO_PASSWORD, authenticate_user, create_user, ensure_demo_user
from backend.database import Base, get_db
from backend.events import sanitize_event_payload
from backend.models import AuditEvent, EventOutbox, IngestionJob, User
from backend.observability import reset_metrics
from backend.pipeline import create_ingestion_job, get_job_for_user, process_outbox_once
from backend.schemas import ActionCreate, ActionUpdate, MeetingUpdate
from backend.services import (
    add_action,
    delete_action,
    delete_meeting,
    export_meeting_report,
    get_meeting,
    record_audit_event,
    update_meeting,
    update_action,
)


SAMPLE_TRANSCRIPT = """
Today is May 9th, 2026, and this is the weekly product sync meeting.
James: I will finalize the Android crash fix by Tuesday.
Emily: Customer support reported hallucination issues in summaries.
"""


def sample_run_meeting_analysis_graph(
    transcript: str,
    follow_up_question: str = "",
    meeting_id: int = 0,
    user_id: int | None = None,
    prompt_version_ids: dict[str, int] | None = None,
) -> dict:
    summary = {
        "overview": "Test summary for local checks.",
        "key_discussion_points": ["Meeting transcript was processed."],
        "decisions_made": [],
    }
    has_grounded_answer = bool(follow_up_question and "budget" not in follow_up_question.lower())
    return {
        "transcript": transcript,
        "cleaned_transcript": transcript.strip(),
        "summary": summary,
        "summary_markdown": "## Overview\nTest summary for local checks.",
        "action_items": [
            {
                "task": "Finalize the Android crash fix",
                "owner": "James",
                "deadline": "Tuesday",
                "evidence": "James: I will finalize the Android crash fix by Tuesday.",
            }
        ],
        "decisions": [],
        "risks": ["Customer support reported hallucination issues in summaries."],
        "follow_up_answer": "James is fixing Android crashes."
        if has_grounded_answer
        else ("Not mentioned" if follow_up_question else ""),
        "follow_up_sources": [
            {
                "chunk_index": 0,
                "content": "James: I will finalize the Android crash fix by Tuesday.",
                "rank": 1,
                "score": 0.99,
            }
        ]
        if has_grounded_answer
        else [],
    }


def create_analyzed_meeting(
    db,
    user_id: int,
    transcript: str = SAMPLE_TRANSCRIPT,
    title: str | None = None,
    follow_up_question: str = "",
):
    job = create_ingestion_job(
        db,
        user_id=user_id,
        source_type="transcript",
        title=title,
        follow_up_question=follow_up_question,
        filename="inline-transcript.txt",
        transcript=transcript,
    )
    process_outbox_once(db)
    process_outbox_once(db)
    if job.meeting_id is None:
        raise AssertionError("Transcript ingestion did not create a meeting")
    return get_meeting(db, job.meeting_id, user_id=user_id)


def ensure_test_database(database_url: str) -> None:
    global TEST_DATABASE_READY, TEST_DATABASE_ERROR
    if TEST_DATABASE_READY:
        return
    if TEST_DATABASE_ERROR is not None:
        raise RuntimeError("Postgres test database is unavailable. Start it with: docker compose up -d postgres") from TEST_DATABASE_ERROR

    url = make_url(database_url)
    if not url.drivername.startswith("postgresql"):
        raise RuntimeError("Backend tests require a Postgres TEST_DATABASE_URL")
    if not url.database or not re.fullmatch(r"[A-Za-z0-9_]+", url.database):
        raise RuntimeError("TEST_DATABASE_URL must include a simple database name")

    admin_database = os.getenv("TEST_POSTGRES_ADMIN_DATABASE", "meeting_agent")
    admin_engine = create_engine(url.set(database=admin_database), isolation_level="AUTOCOMMIT", connect_args={"connect_timeout": 2})
    try:
        with admin_engine.connect() as connection:
            exists = connection.scalar(text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": url.database})
            if not exists:
                connection.execute(text(f'CREATE DATABASE "{url.database}"'))
        TEST_DATABASE_READY = True
    except Exception as exc:
        TEST_DATABASE_ERROR = exc
        raise RuntimeError("Postgres test database is unavailable. Start it with: docker compose up -d postgres") from exc
    finally:
        admin_engine.dispose()


def make_session_factory():
    database_url = os.getenv("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)
    ensure_test_database(database_url)
    engine = create_engine(database_url, connect_args={"connect_timeout": 2})
    with engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        connection.execute(text("DROP TABLE IF EXISTS transcript_chunks CASCADE"))
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, autoflush=False, autocommit=False)


class BackendServiceTests(unittest.TestCase):
    def setUp(self):
        reset_metrics()
        self.original_run_meeting_analysis_graph = services_module.run_meeting_analysis_graph
        services_module.run_meeting_analysis_graph = sample_run_meeting_analysis_graph
        self.engine, self.SessionLocal = make_session_factory()
        self.db = self.SessionLocal()
        self.user = create_user(self.db, "owner@example.com", "password123")
        self.other_user = create_user(self.db, "other@example.com", "password123")

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        services_module.run_meeting_analysis_graph = self.original_run_meeting_analysis_graph

    def test_authenticates_user_with_password(self):
        user = authenticate_user(self.db, "owner@example.com", "password123")
        bad_user = authenticate_user(self.db, "owner@example.com", "wrong-password")

        self.assertEqual(user.id, self.user.id)
        self.assertIsNone(bad_user)

    def test_ensures_demo_user(self):
        demo_user = ensure_demo_user(self.db)
        authenticated = authenticate_user(self.db, DEMO_EMAIL, DEMO_PASSWORD)

        self.assertEqual(demo_user.email, DEMO_EMAIL)
        self.assertEqual(authenticated.id, demo_user.id)

    def test_pipeline_analysis_saves_meeting_actions_and_follow_up_answer(self):
        meeting = create_analyzed_meeting(
            self.db,
            user_id=self.user.id,
            follow_up_question="Who is fixing Android crashes?",
        )

        saved = get_meeting(self.db, meeting.id, user_id=self.user.id)

        self.assertIn("james", saved.follow_up_answer.lower())
        self.assertGreaterEqual(len(saved.actions), 1)

    def test_pipeline_analysis_persists_graph_sources(self):
        meeting = create_analyzed_meeting(
            self.db,
            user_id=self.user.id,
            follow_up_question="Who is fixing Android crashes?",
        )

        saved = get_meeting(self.db, meeting.id, user_id=self.user.id)
        meeting_payload = services_module.meeting_to_dict(saved)

        self.assertEqual(saved.follow_up_answer, "James is fixing Android crashes.")
        self.assertGreaterEqual(len(meeting_payload["follow_up_sources"]), 1)
        self.assertIn("James", meeting_payload["follow_up_sources"][0]["content"])

    def test_follow_up_answer_not_mentioned_without_retrieved_sources(self):
        meeting = create_analyzed_meeting(
            self.db,
            user_id=self.user.id,
            follow_up_question="What was the budget decision?",
        )

        saved = get_meeting(self.db, meeting.id, user_id=self.user.id)
        meeting_payload = services_module.meeting_to_dict(saved)

        self.assertEqual(saved.follow_up_answer, "Not mentioned")
        self.assertEqual(meeting_payload["follow_up_sources"], [])

    def test_not_mentioned_follow_up_does_not_persist_sources(self):
        original_graph = services_module.run_meeting_analysis_graph

        def fake_graph(*args, **kwargs):
            result = sample_run_meeting_analysis_graph(*args, **kwargs)
            result["follow_up_answer"] = "Not mentioned"
            result["follow_up_sources"] = [
                {"chunk_index": 0, "content": "This chunk does not answer the question.", "rank": 1, "score": 0.88}
            ]
            return result

        services_module.run_meeting_analysis_graph = fake_graph
        try:
            meeting = create_analyzed_meeting(
                self.db,
                user_id=self.user.id,
                follow_up_question="When was the meeting?",
            )
        finally:
            services_module.run_meeting_analysis_graph = original_graph

        meeting_payload = services_module.meeting_to_dict(meeting)
        self.assertEqual(meeting.follow_up_answer, "Not mentioned")
        self.assertEqual(meeting_payload["follow_up_sources"], [])

    def test_add_update_and_delete_action_with_owner_check(self):
        meeting = create_analyzed_meeting(self.db, user_id=self.user.id)

        action = add_action(
            self.db,
            meeting.id,
            ActionCreate(task="Send follow-up email", owner="Sarah", deadline="Friday"),
            user_id=self.user.id,
        )
        updated = update_action(self.db, action.id, ActionUpdate(status="Done"), user_id=self.user.id)

        self.assertEqual(updated.status, "Done")

        with self.assertRaises(LookupError):
            update_action(self.db, action.id, ActionUpdate(status="Open"), user_id=self.other_user.id)

        delete_action(self.db, action.id, user_id=self.user.id)

        with self.assertRaises(LookupError):
            update_action(self.db, action.id, ActionUpdate(status="Open"), user_id=self.user.id)

    def test_renames_meeting_with_owner_check(self):
        meeting = create_analyzed_meeting(
            self.db,
            user_id=self.user.id,
            title="Original name",
        )

        updated = update_meeting(self.db, meeting.id, MeetingUpdate(title="Renamed meeting"), user_id=self.user.id)

        self.assertEqual(updated.title, "Renamed meeting")
        with self.assertRaises(LookupError):
            update_meeting(self.db, meeting.id, MeetingUpdate(title="Other user rename"), user_id=self.other_user.id)

    def test_delete_meeting_removes_saved_record(self):
        meeting = create_analyzed_meeting(self.db, user_id=self.user.id)

        with self.assertRaises(LookupError):
            delete_meeting(self.db, meeting.id, user_id=self.other_user.id)

        delete_meeting(self.db, meeting.id, user_id=self.user.id)

        with self.assertRaises(LookupError):
            get_meeting(self.db, meeting.id, user_id=self.user.id)

    def test_export_full_report_returns_docx_bytes(self):
        meeting = create_analyzed_meeting(self.db, user_id=self.user.id)

        report = export_meeting_report(self.db, meeting.id, user_id=self.user.id)

        self.assertTrue(report.startswith(b"PK"))

    def test_ingestion_job_creates_safe_outbox_event(self):
        job = create_ingestion_job(
            self.db,
            user_id=self.user.id,
            source_type="transcript",
            title="Pipeline test",
            filename="inline-transcript.txt",
            transcript=SAMPLE_TRANSCRIPT,
        )

        event = self.db.query(EventOutbox).filter(EventOutbox.key == job.job_id).one()
        envelope = json.loads(event.envelope_json)
        serialized = json.dumps(envelope)

        self.assertEqual(job.status, "queued")
        self.assertEqual(envelope["event_type"], "meeting.uploaded")
        self.assertNotIn(SAMPLE_TRANSCRIPT.strip(), serialized)
        self.assertEqual(envelope["payload"]["source_type"], "transcript")

    def test_stale_queued_job_recovery_processes_published_analysis_event(self):
        job = create_ingestion_job(
            self.db,
            user_id=self.user.id,
            source_type="transcript",
            title="Queued recovery",
            filename="inline-transcript.txt",
            transcript=SAMPLE_TRANSCRIPT,
        )
        process_outbox_once(self.db)
        job = get_job_for_user(self.db, job.job_id, self.user.id, self.user.role)
        analysis_event = (
            self.db.query(EventOutbox)
            .filter(EventOutbox.key == job.job_id, EventOutbox.event_type == pipeline_module.TOPIC_ANALYSIS_REQUESTED)
            .one()
        )
        stale_at = pipeline_module.utc_now() - pipeline_module.timedelta(
            seconds=pipeline_module.QUEUE_RECOVERY_AFTER_SECONDS + 1
        )
        job.updated_at = stale_at
        analysis_event.created_at = stale_at
        analysis_event.publish_status = "published"
        self.db.commit()

        processed = pipeline_module.process_stale_queued_jobs_once(self.db)

        self.assertEqual(processed, 1)
        self.db.refresh(job)
        self.db.refresh(analysis_event)
        self.assertEqual(job.status, "completed")
        self.assertEqual(analysis_event.publish_status, "processed")

        pipeline_module.process_event_envelope(self.db, json.loads(analysis_event.envelope_json))
        self.db.refresh(job)
        self.assertEqual(job.status, "completed")

    def test_event_payload_redacts_sensitive_fields(self):
        payload = sanitize_event_payload(
            {
                "transcript": "raw transcript",
                "api_key": "secret-key",
                "source_uri": "/private/upload.wav",
                "source_type": "audio",
            }
        )

        self.assertEqual(payload["transcript"], "[redacted]")
        self.assertEqual(payload["api_key"], "[redacted]")
        self.assertEqual(payload["source_uri"], "[redacted]")
        self.assertEqual(payload["source_type"], "audio")

    def test_cross_user_job_access_is_denied(self):
        job = create_ingestion_job(
            self.db,
            user_id=self.user.id,
            source_type="transcript",
            transcript=SAMPLE_TRANSCRIPT,
        )

        with self.assertRaises(LookupError):
            get_job_for_user(self.db, job.job_id, self.other_user.id, self.other_user.role)

    def test_admin_cannot_restore_another_users_job(self):
        job = create_ingestion_job(
            self.db,
            user_id=self.other_user.id,
            source_type="transcript",
            transcript=SAMPLE_TRANSCRIPT,
        )

        self.assertEqual(self.user.role, "admin")
        with self.assertRaises(LookupError):
            get_job_for_user(self.db, job.job_id, self.user.id, self.user.role)


class BackendApiTests(unittest.TestCase):
    def setUp(self):
        self.original_run_meeting_analysis_graph = services_module.run_meeting_analysis_graph
        services_module.run_meeting_analysis_graph = sample_run_meeting_analysis_graph
        self.engine, self.SessionLocal = make_session_factory()

        def override_db():
            db = self.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_db
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.engine.dispose()
        services_module.run_meeting_analysis_graph = self.original_run_meeting_analysis_graph
        reset_metrics()

    def auth_headers(self, email: str = "api@example.com") -> dict[str, str]:
        response = self.client.post(
            "/api/auth/register",
            json={"email": email, "password": "password123"},
        )
        if response.status_code == 400:
            response = self.client.post(
                "/api/auth/login",
                json={"email": email, "password": "password123"},
            )
        self.assertEqual(response.status_code, 200)
        token = response.json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    def process_pipeline_events(self, passes: int = 2) -> int:
        db = self.SessionLocal()
        try:
            processed = 0
            for _ in range(passes):
                processed += process_outbox_once(db)
            return processed
        finally:
            db.close()

    def ingest_transcript(
        self,
        headers: dict[str, str],
        transcript: str = SAMPLE_TRANSCRIPT,
        title: str = "Pipeline transcript",
        follow_up_question: str = "",
    ) -> dict:
        response = self.client.post(
            "/api/meetings/ingest",
            headers=headers,
            data={
                "title": title,
                "transcript": transcript,
                "follow_up_question": follow_up_question,
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.process_pipeline_events()

        detail = self.client.get(f"/api/jobs/{payload['job_id']}", headers=headers)
        self.assertEqual(detail.status_code, 200)
        job = detail.json()
        self.assertEqual(job["status"], "completed")
        self.assertIsNotNone(job["meeting_id"])
        return job

    def test_auth_register_login_and_me(self):
        register_response = self.client.post(
            "/api/auth/register",
            json={"email": "new@example.com", "password": "password123"},
        )
        self.assertEqual(register_response.status_code, 200)
        token = register_response.json()["access_token"]

        login_response = self.client.post(
            "/api/auth/login",
            json={"email": "new@example.com", "password": "password123"},
        )
        self.assertEqual(login_response.status_code, 200)

        me_response = self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(me_response.status_code, 200)
        self.assertEqual(me_response.json()["email"], "new@example.com")

    def test_auth_demo_returns_valid_prefilled_account(self):
        response = self.client.post("/api/auth/demo")
        self.assertEqual(response.status_code, 200)
        token = response.json()["access_token"]
        self.assertEqual(response.json()["user"]["email"], DEMO_EMAIL)

        login_response = self.client.post(
            "/api/auth/login",
            json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD},
        )
        self.assertEqual(login_response.status_code, 200)

        me_response = self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(me_response.status_code, 200)
        self.assertEqual(me_response.json()["email"], DEMO_EMAIL)

    def test_protected_endpoints_reject_missing_token(self):
        response = self.client.get("/api/meetings")
        metrics_response = self.client.get("/api/metrics")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(metrics_response.status_code, 401)

    def test_metrics_endpoint_reports_local_ops_counters(self):
        headers = self.auth_headers("metrics@example.com")
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertIn("X-Request-ID", response.headers)

        db = self.SessionLocal()
        try:
            meeting = create_analyzed_meeting(db, user_id=self.user.id)
            meeting.generation_latency_ms = 42000
            db.commit()
        finally:
            db.close()

        metrics_response = self.client.get("/api/metrics", headers=headers)

        self.assertEqual(metrics_response.status_code, 200)
        payload = metrics_response.json()
        self.assertIn("uptime_seconds", payload)
        self.assertIn("api.requests", payload["counters"])
        self.assertEqual(payload["latencies"]["analysis.graph.run"]["count"], 1)
        self.assertEqual(payload["latencies"]["analysis.graph.run"]["average_seconds"], 42.0)
        self.assertEqual(payload["latencies"]["analysis.graph.run"]["max_seconds"], 42.0)
        self.assertIn("sla_targets", payload)
        self.assertEqual(payload["sla_targets"]["scope"], "production_style_objectives")
        self.assertIn("integrations", payload)
        self.assertIn("models", payload)

        prometheus_response = self.client.get("/metrics")
        self.assertEqual(prometheus_response.status_code, 200)
        self.assertIn("meeting_agent", prometheus_response.text)

    def test_governance_prompt_endpoint_reports_registered_prompts(self):
        headers = self.auth_headers("prompt-admin@example.com")
        response = self.client.get("/api/governance/prompts", headers=headers)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload), 3)
        self.assertEqual(
            {(prompt["task_type"], prompt["prompt_id"]) for prompt in payload},
            {
                ("action_and_risk_extraction", "meeting_insights"),
                ("rag_qa", "grounded_follow_up"),
                ("summary", "meeting_summary"),
            },
        )
        self.assertEqual(
            [prompt["version"] for prompt in payload if prompt["prompt_id"] == "grounded_follow_up"],
            ["2026-05-ops-v2"],
        )
        self.assertIn("template_hash", payload[0])
        self.assertNotIn("status", payload[0])

    def test_prompt_eval_and_approve_endpoints_are_removed(self):
        headers = self.auth_headers("prompt-admin@example.com")
        openapi_paths = self.client.get("/openapi.json").json()["paths"]

        self.assertNotIn("/api/evals/run", openapi_paths)
        self.assertNotIn("/api/evals/runs", openapi_paths)
        self.assertTrue(
            all(not path.endswith("/approve") for path in openapi_paths),
            "Prompt approval endpoints should not be exposed.",
        )
        self.assertIn(self.client.post("/api/evals/run", headers=headers).status_code, {404, 405})
        self.assertIn(self.client.get("/api/evals/runs", headers=headers).status_code, {404, 405})
        self.assertIn(self.client.post("/api/governance/prompts/1/approve", headers=headers).status_code, {404, 405})

    def test_pipeline_operations_reports_each_worker(self):
        headers = self.auth_headers("worker-admin@example.com")
        db = self.SessionLocal()
        try:
            user = db.query(User).filter(User.email == "worker-admin@example.com").one()
            db.add(
                IngestionJob(
                    job_id="abc123",
                    user_id=user.id,
                    source_type="inline",
                    filename="worker.txt",
                    status="processing",
                    current_step="analysis_running",
                )
            )
            pipeline_module.record_worker_heartbeat(
                db,
                worker_id="backend-worker:one",
                display_name="backend-worker one",
                hostname="one",
                mode="kafka",
                status="idle",
                processed_delta=3,
            )
            pipeline_module.record_worker_heartbeat(
                db,
                worker_id="backend-worker:two",
                display_name="backend-worker two",
                hostname="two",
                mode="kafka",
                status="processing",
                current_topic="analysis.requested",
                current_job_id="abc123",
                current_event_type="analysis.requested",
            )
            db.commit()
        finally:
            db.close()

        response = self.client.get("/api/operations/pipeline", headers=headers)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        workers = {worker["worker_id"]: worker for worker in payload["workers"]}
        self.assertEqual(payload["expected_worker_count"], 3)
        self.assertEqual(payload["reporting_worker_count"], 2)
        self.assertEqual(payload["missing_worker_count"], 1)
        self.assertEqual(payload["stale_worker_count"], 0)
        self.assertEqual(len(payload["workers"]), 3)
        self.assertEqual(workers["backend-worker:one"]["status"], "idle")
        self.assertEqual(workers["backend-worker:one"]["processed_count"], 3)
        self.assertEqual(workers["backend-worker:two"]["status"], "processing")
        self.assertEqual(workers["backend-worker:two"]["current_job_id"], "abc123")
        self.assertEqual(workers["missing-worker:3"]["status"], "missing")

    def test_pipeline_operations_hides_retired_worker_heartbeats_after_restart(self):
        headers = self.auth_headers("worker-restart-admin@example.com")
        db = self.SessionLocal()
        try:
            older_seen_at = pipeline_module.utc_now() - pipeline_module.timedelta(seconds=60)
            for index in range(3):
                retired = pipeline_module.record_worker_heartbeat(
                    db,
                    worker_id=f"backend-worker:retired-{index}",
                    display_name=f"backend-worker retired {index}",
                    hostname=f"retired-{index}",
                    mode="kafka",
                    status="idle",
                )
                retired.last_seen_at = older_seen_at
                retired.updated_at = older_seen_at
            for index in range(3):
                pipeline_module.record_worker_heartbeat(
                    db,
                    worker_id=f"backend-worker:current-{index}",
                    display_name=f"backend-worker current {index}",
                    hostname=f"current-{index}",
                    mode="kafka",
                    status="idle",
                )
            db.commit()
        finally:
            db.close()

        response = self.client.get("/api/operations/pipeline", headers=headers)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        worker_ids = {worker["worker_id"] for worker in payload["workers"]}
        self.assertEqual(payload["reporting_worker_count"], 3)
        self.assertEqual(payload["missing_worker_count"], 0)
        self.assertEqual(payload["stale_worker_count"], 0)
        self.assertEqual(len(payload["workers"]), 3)
        self.assertTrue(all(worker_id.startswith("backend-worker:current-") for worker_id in worker_ids))

    def test_worker_heartbeat_pruning_keeps_newest_ten_per_worker_group(self):
        db = self.SessionLocal()
        try:
            for index in range(12):
                pipeline_module.record_worker_heartbeat(
                    db,
                    worker_id=f"backend-worker:restart-{index}",
                    display_name=f"backend-worker restart {index}",
                    hostname=f"restart-{index}",
                    mode="kafka",
                    status="idle",
                )
            db.commit()
            worker_ids = {
                worker.worker_id
                for worker in db.query(pipeline_module.WorkerHeartbeat)
                .filter(pipeline_module.WorkerHeartbeat.worker_id.like("backend-worker:%"))
                .all()
            }
        finally:
            db.close()

        self.assertEqual(len(worker_ids), 10)
        self.assertNotIn("backend-worker:restart-0", worker_ids)
        self.assertNotIn("backend-worker:restart-1", worker_ids)
        self.assertIn("backend-worker:restart-11", worker_ids)

    def test_pipeline_operations_reports_missing_workers_when_no_heartbeat_exists(self):
        headers = self.auth_headers("missing-worker-admin@example.com")

        response = self.client.get("/api/operations/pipeline", headers=headers)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["expected_worker_count"], 3)
        self.assertEqual(payload["reporting_worker_count"], 0)
        self.assertEqual(payload["missing_worker_count"], 3)
        self.assertEqual(payload["stale_worker_count"], 0)
        self.assertEqual([worker["status"] for worker in payload["workers"]], ["missing", "missing", "missing"])

    def test_pipeline_operations_keeps_job_counts_separate_from_worker_heartbeats(self):
        headers = self.auth_headers("queued-work-admin@example.com")
        db = self.SessionLocal()
        try:
            user = db.query(User).filter(User.email == "queued-work-admin@example.com").one()
            db.add(
                IngestionJob(
                    job_id="processing-without-heartbeat",
                    user_id=user.id,
                    source_type="inline",
                    filename="workerless.txt",
                    status="processing",
                    current_step="analysis_running",
                )
            )
            db.commit()
        finally:
            db.close()

        response = self.client.get("/api/operations/pipeline", headers=headers)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["job_counts"].get("processing"), 1)
        self.assertEqual(payload["reporting_worker_count"], 0)
        self.assertEqual(payload["missing_worker_count"], 3)
        self.assertEqual([worker["status"] for worker in payload["workers"]], ["missing", "missing", "missing"])

    def test_pipeline_operations_marks_stale_workers_as_not_reporting(self):
        headers = self.auth_headers("stale-worker-admin@example.com")
        db = self.SessionLocal()
        try:
            worker = pipeline_module.record_worker_heartbeat(
                db,
                worker_id="backend-worker:stale",
                display_name="backend-worker stale",
                hostname="stale",
                mode="kafka",
                status="idle",
            )
            stale_at = pipeline_module.utc_now() - pipeline_module.timedelta(
                seconds=pipeline_module.WORKER_STALE_AFTER_SECONDS + 10
            )
            worker.last_seen_at = stale_at
            worker.updated_at = stale_at
            db.commit()
        finally:
            db.close()

        response = self.client.get("/api/operations/pipeline", headers=headers)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        workers = {worker["worker_id"]: worker for worker in payload["workers"]}
        self.assertEqual(payload["reporting_worker_count"], 0)
        self.assertEqual(payload["stale_worker_count"], 1)
        self.assertEqual(payload["missing_worker_count"], 2)
        self.assertEqual(workers["backend-worker:stale"]["status"], "stale")

    def test_pipeline_operations_requires_admin(self):
        self.auth_headers("pipeline-admin@example.com")
        regular_headers = self.auth_headers("pipeline-regular@example.com")

        response = self.client.get("/api/operations/pipeline", headers=regular_headers)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "Permission denied")

    def test_pipeline_operations_reports_systemwide_jobs(self):
        admin_headers = self.auth_headers("queue-admin@example.com")
        self.auth_headers("queue-other@example.com")
        db = self.SessionLocal()
        try:
            admin = db.query(User).filter(User.email == "queue-admin@example.com").one()
            other = db.query(User).filter(User.email == "queue-other@example.com").one()
            db.add_all(
                [
                    IngestionJob(
                        job_id="admin-processing-job",
                        user_id=admin.id,
                        source_type="inline",
                        filename="admin.txt",
                        status="processing",
                        current_step="analysis_running",
                    ),
                    IngestionJob(
                        job_id="other-processing-job",
                        user_id=other.id,
                        source_type="inline",
                        filename="other.txt",
                        status="processing",
                        current_step="analysis_running",
                    ),
                    IngestionJob(
                        job_id="other-failed-job",
                        user_id=other.id,
                        source_type="inline",
                        filename="failed.txt",
                        status="failed",
                        current_step="analysis_failed",
                    ),
                ]
            )
            pipeline_module.record_worker_heartbeat(
                db,
                worker_id="backend-worker:other",
                display_name="backend-worker other",
                hostname="other",
                mode="kafka",
                status="processing",
                current_job_id="other-processing-job",
            )
            db.commit()
        finally:
            db.close()

        response = self.client.get("/api/operations/pipeline", headers=admin_headers)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["job_counts"].get("processing"), 2)
        self.assertEqual(payload["job_counts"].get("failed"), 1)
        self.assertEqual(payload["failed_job_count"], 1)
        self.assertEqual([job["job_id"] for job in payload["failed_jobs"]], ["other-failed-job"])
        self.assertEqual(payload["workers"][0]["current_job_id"], "other-processing-job")

    def test_cross_user_job_api_reports_not_found_without_permission_audit(self):
        self.auth_headers("job-owner@example.com")
        other_headers = self.auth_headers("job-other@example.com")
        db = self.SessionLocal()
        try:
            owner = db.query(User).filter(User.email == "job-owner@example.com").one()
            job = create_ingestion_job(
                db,
                user_id=owner.id,
                source_type="transcript",
                transcript=SAMPLE_TRANSCRIPT,
            )
            job_id = job.job_id
        finally:
            db.close()

        response = self.client.get(f"/api/jobs/{job_id}", headers=other_headers)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Job not found")
        db = self.SessionLocal()
        try:
            permission_events = list(
                db.query(AuditEvent).filter(
                    AuditEvent.action == "permission.denied",
                    AuditEvent.resource_type == "ingestion_job",
                    AuditEvent.resource_id == job_id,
                )
            )
        finally:
            db.close()
        self.assertEqual(permission_events, [])

    def test_unknown_ai_run_reports_invalid_without_permission_audit(self):
        headers = self.auth_headers("ai-run-admin@example.com")
        response = self.client.get("/api/ai/runs/not-a-real-run", headers=headers)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Run ID invalid or not found.")

        db = self.SessionLocal()
        try:
            permission_events = list(
                db.query(AuditEvent).filter(AuditEvent.action == "permission.denied", AuditEvent.resource_type == "ai_run")
            )
        finally:
            db.close()
        self.assertEqual(permission_events, [])

    def test_audit_endpoint_reports_user_events(self):
        headers = self.auth_headers("audit@example.com")
        ingest_response = self.client.post(
            "/api/meetings/ingest",
            headers=headers,
            data={"transcript": SAMPLE_TRANSCRIPT},
        )
        self.assertEqual(ingest_response.status_code, 200)

        response = self.client.get("/api/audit/events", headers=headers)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["page"], 1)
        self.assertEqual(payload["page_size"], 20)
        event_types = [event["event_type"] for event in payload["items"]]
        self.assertIn("auth.register", event_types)
        self.assertIn("meeting.ingest", event_types)

    def test_meeting_ingest_audit_event_includes_primary_run_id_after_analysis(self):
        headers = self.auth_headers("audit-run@example.com")
        job = self.ingest_transcript(headers, title="Run linked audit")
        db = self.SessionLocal()
        try:
            meeting = services_module.get_meeting(db, job["meeting_id"], user_id=None)
            meeting.ai_run_ids_json = json.dumps(["run123456789"])
            db.commit()
        finally:
            db.close()

        response = self.client.get("/api/audit/events", headers=headers)

        self.assertEqual(response.status_code, 200)
        ingest_events = [
            event
            for event in response.json()["items"]
            if event["event_type"] == "meeting.ingest" and event["resource_id"] == job["job_id"]
        ]
        self.assertEqual(len(ingest_events), 1)
        self.assertEqual(ingest_events[0]["run_id"], "run123456789")

    def test_audit_endpoint_paginates_events(self):
        headers = self.auth_headers("audit-pages@example.com")
        db = self.SessionLocal()
        try:
            user = db.query(User).filter(User.email == "audit-pages@example.com").one()
            for index in range(45):
                record_audit_event(
                    db,
                    f"custom.audit.{index:02d}",
                    user_id=user.id,
                    entity_type="custom",
                    entity_id=index,
                )
        finally:
            db.close()

        first_page = self.client.get("/api/audit/events?page=1&page_size=20", headers=headers)
        second_page = self.client.get("/api/audit/events?page=2&page_size=20", headers=headers)

        self.assertEqual(first_page.status_code, 200)
        self.assertEqual(second_page.status_code, 200)
        first_payload = first_page.json()
        second_payload = second_page.json()
        self.assertEqual(first_payload["page"], 1)
        self.assertEqual(first_payload["page_size"], 20)
        self.assertEqual(len(first_payload["items"]), 20)
        self.assertEqual(second_payload["page"], 2)
        self.assertEqual(len(second_payload["items"]), 20)
        self.assertGreaterEqual(first_payload["total"], 45)
        self.assertGreaterEqual(first_payload["total_pages"], 3)
        self.assertGreater(
            min(event["id"] for event in first_payload["items"]),
            max(event["id"] for event in second_payload["items"]),
        )

    def test_audit_endpoint_regular_user_sees_only_own_events(self):
        self.auth_headers("first-admin@example.com")
        regular_headers = self.auth_headers("regular-audit@example.com")
        db = self.SessionLocal()
        try:
            admin = db.query(User).filter(User.email == "first-admin@example.com").one()
            regular = db.query(User).filter(User.email == "regular-audit@example.com").one()
            record_audit_event(db, "admin.only", user_id=admin.id, entity_type="custom")
            record_audit_event(db, "regular.only", user_id=regular.id, entity_type="custom")
        finally:
            db.close()

        response = self.client.get("/api/audit/events?page=1&page_size=20", headers=regular_headers)

        self.assertEqual(response.status_code, 200)
        event_types = [event["event_type"] for event in response.json()["items"]]
        self.assertIn("regular.only", event_types)
        self.assertNotIn("admin.only", event_types)

    def test_api_analyze_endpoint_is_removed(self):
        headers = self.auth_headers("removed@example.com")
        response = self.client.post(
            "/api/meetings/analyze",
            headers=headers,
            json={"transcript": SAMPLE_TRANSCRIPT},
        )
        openapi_paths = self.client.get("/openapi.json").json()["paths"]

        self.assertNotIn("/api/meetings/analyze", openapi_paths)
        self.assertIn(response.status_code, {404, 405})

    def test_api_ingest_pipeline_retrieve_update_delete_and_export(self):
        headers = self.auth_headers()
        job = self.ingest_transcript(
            headers,
            follow_up_question="Who is fixing Android crashes?",
        )

        detail_response = self.client.get(f"/api/meetings/{job['meeting_id']}", headers=headers)
        self.assertEqual(detail_response.status_code, 200)
        meeting = detail_response.json()
        self.assertIn("follow_up_sources", meeting)
        self.assertGreaterEqual(len(meeting["follow_up_sources"]), 1)
        self.assertIn("run_id", meeting)
        self.assertNotIn("citations", meeting)
        self.assertNotIn("validation_status", meeting)
        self.assertNotIn("evidence_status", meeting)
        self.assertNotIn("needs_review", meeting)

        rename_response = self.client.patch(
            f"/api/meetings/{meeting['id']}",
            headers=headers,
            json={"title": "Renamed meeting"},
        )
        self.assertEqual(rename_response.status_code, 200)
        self.assertEqual(rename_response.json()["title"], "Renamed meeting")

        add_response = self.client.post(
            f"/api/meetings/{meeting['id']}/actions",
            headers=headers,
            json={"task": "Prepare demo notes", "owner": "Ravi", "deadline": "Tomorrow"},
        )
        self.assertEqual(add_response.status_code, 200)
        action = add_response.json()

        patch_response = self.client.patch(f"/api/actions/{action['id']}", headers=headers, json={"status": "Done"})
        self.assertEqual(patch_response.status_code, 200)
        self.assertEqual(patch_response.json()["status"], "Done")

        export_response = self.client.get(f"/api/meetings/{meeting['id']}/export", headers=headers)
        self.assertEqual(export_response.status_code, 200)
        self.assertTrue(export_response.content.startswith(b"PK"))

        delete_response = self.client.delete(f"/api/actions/{action['id']}", headers=headers)
        self.assertEqual(delete_response.status_code, 204)

        meeting_delete_response = self.client.delete(f"/api/meetings/{meeting['id']}", headers=headers)
        self.assertEqual(meeting_delete_response.status_code, 204)

        missing_response = self.client.get(f"/api/meetings/{meeting['id']}", headers=headers)
        self.assertEqual(missing_response.status_code, 404)

    def test_api_blocks_cross_user_meeting_access(self):
        owner_headers = self.auth_headers("owner@example.com")
        other_headers = self.auth_headers("other@example.com")
        job = self.ingest_transcript(owner_headers)
        meeting_id = job["meeting_id"]

        response = self.client.get(f"/api/meetings/{meeting_id}", headers=other_headers)

        self.assertEqual(response.status_code, 404)

    def test_api_transcription_job_returns_transcript_after_worker_finishes(self):
        headers = self.auth_headers()
        original_publish_pending = api_module.publish_pending_outbox
        original_transcribe = pipeline_module.transcribe_audio
        api_module.publish_pending_outbox = lambda db, limit=25: 0
        pipeline_module.transcribe_audio = lambda uploaded_file, filename: f"Durable transcript from {filename}"
        try:
            response = self.client.post(
                "/api/meetings/transcribe/jobs",
                headers=headers,
                files={"file": ("meeting.mp3", b"sample audio bytes", "audio/mpeg")},
            )
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["status"], "queued")
            self.assertEqual(payload["current_step"], "transcription_queued")
            self.assertEqual(payload["file_size_bytes"], len(b"sample audio bytes"))

            self.process_pipeline_events(passes=1)

            detail = self.client.get(f"/api/jobs/{payload['job_id']}", headers=headers)
            self.assertEqual(detail.status_code, 200)
            self.assertEqual(detail.json()["file_size_bytes"], len(b"sample audio bytes"))
            self.assertEqual(detail.json()["status"], "completed")
            self.assertEqual(detail.json()["current_step"], "transcription_completed")

            transcript = self.client.get(f"/api/jobs/{payload['job_id']}/transcript", headers=headers)
            self.assertEqual(transcript.status_code, 200)
            self.assertEqual(transcript.json()["transcript"], "Durable transcript from meeting.mp3")
        finally:
            pipeline_module.transcribe_audio = original_transcribe
            api_module.publish_pending_outbox = original_publish_pending

    def test_latest_transcription_job_returns_current_user_latest(self):
        headers = self.auth_headers("latest-transcription@example.com")
        other_headers = self.auth_headers("other-transcription@example.com")
        original_publish_pending = api_module.publish_pending_outbox
        api_module.publish_pending_outbox = lambda db, limit=25: 0
        try:
            first = self.client.post(
                "/api/meetings/transcribe/jobs",
                headers=headers,
                files={"file": ("first.mp3", b"first audio", "audio/mpeg")},
            )
            second = self.client.post(
                "/api/meetings/transcribe/jobs",
                headers=headers,
                files={"file": ("second.mp3", b"second audio", "audio/mpeg")},
            )
            other = self.client.post(
                "/api/meetings/transcribe/jobs",
                headers=other_headers,
                files={"file": ("other.mp3", b"other audio", "audio/mpeg")},
            )
        finally:
            api_module.publish_pending_outbox = original_publish_pending

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(other.status_code, 200)

        latest = self.client.get("/api/jobs/latest/transcription", headers=headers)
        other_latest = self.client.get("/api/jobs/latest/transcription", headers=other_headers)

        self.assertEqual(latest.status_code, 200)
        self.assertEqual(latest.json()["job_id"], second.json()["job_id"])
        self.assertEqual(latest.json()["filename"], "second.mp3")
        self.assertEqual(latest.json()["source_type"], "transcription_audio")
        self.assertEqual(other_latest.status_code, 200)
        self.assertEqual(other_latest.json()["job_id"], other.json()["job_id"])

    def test_api_ingest_audio_routes_through_transcription_before_analysis(self):
        headers = self.auth_headers()
        original_publish_pending = api_module.publish_pending_outbox
        original_transcribe = pipeline_module.transcribe_audio
        api_module.publish_pending_outbox = lambda db, limit=25: 0
        pipeline_module.transcribe_audio = lambda uploaded_file, filename: f"Audio transcript from {filename}"
        try:
            response = self.client.post(
                "/api/meetings/ingest",
                headers=headers,
                data={"title": "Audio pipeline", "follow_up_question": "Who owns the Android fix?"},
                files={"file": ("meeting.mp3", b"sample audio bytes", "audio/mpeg")},
            )
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["status"], "queued")
            self.assertEqual(payload["current_step"], "ingestion_event")
            self.assertEqual(payload["file_size_bytes"], len(b"sample audio bytes"))

            self.process_pipeline_events(passes=1)
            routed = self.client.get(f"/api/jobs/{payload['job_id']}", headers=headers)
            self.assertEqual(routed.status_code, 200)
            self.assertEqual(routed.json()["status"], "queued")
            self.assertEqual(routed.json()["current_step"], "transcription_queued")
            self.assertEqual(routed.json()["file_size_bytes"], len(b"sample audio bytes"))
            self.assertIsNone(routed.json()["meeting_id"])

            self.process_pipeline_events(passes=2)
            completed = self.client.get(f"/api/jobs/{payload['job_id']}", headers=headers)
            self.assertEqual(completed.status_code, 200)
            self.assertEqual(completed.json()["status"], "completed")
            self.assertEqual(completed.json()["current_step"], "analysis_completed")
            self.assertIsNotNone(completed.json()["meeting_id"])

            meeting = self.client.get(f"/api/meetings/{completed.json()['meeting_id']}", headers=headers)
            self.assertEqual(meeting.status_code, 200)
            self.assertIn("Audio transcript from meeting.mp3", meeting.json()["transcript"])

            db = self.SessionLocal()
            try:
                event_types = [
                    event.event_type
                    for event in db.query(EventOutbox).filter(EventOutbox.key == payload["job_id"]).all()
                ]
            finally:
                db.close()
            self.assertIn("meeting.uploaded", event_types)
            self.assertIn("transcription.requested", event_types)
            self.assertIn("analysis.requested", event_types)
        finally:
            pipeline_module.transcribe_audio = original_transcribe
            api_module.publish_pending_outbox = original_publish_pending

    def test_api_ingest_transcript_creates_job(self):
        headers = self.auth_headers()
        original_publish_pending = api_module.publish_pending_outbox
        api_module.publish_pending_outbox = lambda db, limit=25: 0
        try:
            response = self.client.post(
                "/api/meetings/ingest",
                headers=headers,
                data={
                    "title": "Pipeline transcript",
                    "transcript": SAMPLE_TRANSCRIPT,
                    "follow_up_question": "Who owns the Android fix?",
                },
            )
        finally:
            api_module.publish_pending_outbox = original_publish_pending

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("job_id", payload)
        self.assertEqual(payload["status"], "queued")
        self.assertEqual(payload["current_step"], "ingestion_event")

        detail = self.client.get(f"/api/jobs/{payload['job_id']}", headers=headers)
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["job_id"], payload["job_id"])


if __name__ == "__main__":
    unittest.main()

