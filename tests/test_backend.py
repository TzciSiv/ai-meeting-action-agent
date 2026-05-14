import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import backend.api as api_module
import backend.local_model as local_model_module
import backend.services as services_module
from backend.api import app
from backend.auth import DEMO_EMAIL, DEMO_PASSWORD, authenticate_user, create_user, ensure_demo_user
from backend.database import Base, get_db
from backend.schemas import ActionCreate, ActionUpdate, MeetingAnalyzeRequest, MeetingUpdate
from backend.services import (
    add_action,
    create_meeting_from_analysis,
    delete_action,
    delete_meeting,
    export_meeting_report,
    get_meeting,
    update_meeting,
    update_action,
)


SAMPLE_TRANSCRIPT = """
Today is May 9th, 2026, and this is the weekly product sync meeting.
James: I will finalize the Android crash fix by Tuesday.
Emily: Customer support reported hallucination issues in summaries.
"""


def sample_summary_response(cleaned_transcript: str, follow_up_question: str = "") -> dict:
    summary = {
        "overview": "Test summary for local checks.",
        "key_discussion_points": ["Meeting transcript was processed."],
        "decisions_made": [],
        "action_items": [
            {
                "task": "Finalize the Android crash fix",
                "owner": "James",
                "deadline": "Tuesday",
            }
        ],
    }
    if follow_up_question:
        summary["follow_up_answer"] = "James is fixing Android crashes."
    return summary


def sample_local_summary(cleaned_transcript: str, *args, **kwargs) -> dict:
    return {
        "overview": "Local model summary for local checks.",
        "key_discussion_points": ["Meeting transcript was processed locally."],
        "decisions_made": [],
        "action_items": [
            {
                "task": "Finalize the Android crash fix",
                "owner": "James",
                "deadline": "Tuesday",
            }
        ],
    }


def sample_follow_up_answer(cleaned_transcript: str, question: str) -> str:
    return "James is fixing Android crashes."


def sample_run_action_agent(cleaned_transcript: str, summary: dict) -> dict:
    return {
        "action_items": [
            {
                "task": "Finalize the Android crash fix",
                "owner": "James",
                "deadline": "Tuesday",
                "evidence": "James: I will finalize the Android crash fix by Tuesday.",
            }
        ],
        "decisions": summary.get("decisions_made", []),
        "risks": ["Customer support reported hallucination issues in summaries."],
    }


def make_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, autoflush=False, autocommit=False)


class BackendServiceTests(unittest.TestCase):
    def setUp(self):
        self.original_summarize_transcript = services_module.summarize_transcript
        self.original_answer_follow_up_question = services_module.answer_follow_up_question
        self.original_local_summary = local_model_module.summarize_with_local_model
        self.original_run_action_agent = services_module.run_action_agent
        services_module.summarize_transcript = sample_summary_response
        services_module.answer_follow_up_question = sample_follow_up_answer
        services_module.run_action_agent = sample_run_action_agent
        local_model_module.summarize_with_local_model = sample_local_summary
        self.engine, self.SessionLocal = make_session_factory()
        self.db = self.SessionLocal()
        self.user = create_user(self.db, "owner@example.com", "password123")
        self.other_user = create_user(self.db, "other@example.com", "password123")

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        local_model_module.summarize_with_local_model = self.original_local_summary
        services_module.run_action_agent = self.original_run_action_agent
        services_module.answer_follow_up_question = self.original_answer_follow_up_question
        services_module.summarize_transcript = self.original_summarize_transcript

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

    def test_analyze_meeting_saves_meeting_actions_and_follow_up_answer(self):
        meeting = create_meeting_from_analysis(
            self.db,
            MeetingAnalyzeRequest(
                transcript=SAMPLE_TRANSCRIPT,
                follow_up_question="Who is fixing Android crashes?",
            ),
            user_id=self.user.id,
        )

        saved = get_meeting(self.db, meeting.id, user_id=self.user.id)

        self.assertIn("james", saved.follow_up_answer.lower())
        self.assertGreaterEqual(len(saved.actions), 1)

    def test_local_summary_uses_gpt_for_follow_up_answer(self):
        meeting = create_meeting_from_analysis(
            self.db,
            MeetingAnalyzeRequest(
                transcript=SAMPLE_TRANSCRIPT,
                follow_up_question="Who is fixing Android crashes?",
                summary_engine="local",
            ),
            user_id=self.user.id,
        )

        saved = get_meeting(self.db, meeting.id, user_id=self.user.id)

        self.assertEqual(saved.follow_up_answer, "James is fixing Android crashes.")
        self.assertIn("Local model summary", saved.summary_markdown)

    def test_add_update_and_delete_action_with_owner_check(self):
        meeting = create_meeting_from_analysis(
            self.db,
            MeetingAnalyzeRequest(transcript=SAMPLE_TRANSCRIPT),
            user_id=self.user.id,
        )

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
        meeting = create_meeting_from_analysis(
            self.db,
            MeetingAnalyzeRequest(transcript=SAMPLE_TRANSCRIPT, title="Original name"),
            user_id=self.user.id,
        )

        updated = update_meeting(self.db, meeting.id, MeetingUpdate(title="Renamed meeting"), user_id=self.user.id)

        self.assertEqual(updated.title, "Renamed meeting")
        with self.assertRaises(LookupError):
            update_meeting(self.db, meeting.id, MeetingUpdate(title="Other user rename"), user_id=self.other_user.id)

    def test_delete_meeting_removes_saved_record(self):
        meeting = create_meeting_from_analysis(
            self.db,
            MeetingAnalyzeRequest(transcript=SAMPLE_TRANSCRIPT),
            user_id=self.user.id,
        )

        with self.assertRaises(LookupError):
            delete_meeting(self.db, meeting.id, user_id=self.other_user.id)

        delete_meeting(self.db, meeting.id, user_id=self.user.id)

        with self.assertRaises(LookupError):
            get_meeting(self.db, meeting.id, user_id=self.user.id)

    def test_export_full_report_returns_docx_bytes(self):
        meeting = create_meeting_from_analysis(
            self.db,
            MeetingAnalyzeRequest(transcript=SAMPLE_TRANSCRIPT),
            user_id=self.user.id,
        )

        report = export_meeting_report(self.db, meeting.id, user_id=self.user.id)

        self.assertTrue(report.startswith(b"PK"))


class BackendApiTests(unittest.TestCase):
    def setUp(self):
        self.original_summarize_transcript = services_module.summarize_transcript
        self.original_answer_follow_up_question = services_module.answer_follow_up_question
        self.original_local_summary = local_model_module.summarize_with_local_model
        self.original_run_action_agent = services_module.run_action_agent
        services_module.summarize_transcript = sample_summary_response
        services_module.answer_follow_up_question = sample_follow_up_answer
        services_module.run_action_agent = sample_run_action_agent
        local_model_module.summarize_with_local_model = sample_local_summary
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
        local_model_module.summarize_with_local_model = self.original_local_summary
        services_module.run_action_agent = self.original_run_action_agent
        services_module.answer_follow_up_question = self.original_answer_follow_up_question
        services_module.summarize_transcript = self.original_summarize_transcript

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

        self.assertEqual(response.status_code, 401)

    def test_api_analyze_retrieve_update_delete_and_export(self):
        headers = self.auth_headers()
        analyze_response = self.client.post(
            "/api/meetings/analyze",
            headers=headers,
            json={
                "transcript": SAMPLE_TRANSCRIPT,
                "follow_up_question": "Who is fixing Android crashes?",
            },
        )
        self.assertEqual(analyze_response.status_code, 200)
        meeting = analyze_response.json()

        detail_response = self.client.get(f"/api/meetings/{meeting['id']}", headers=headers)
        self.assertEqual(detail_response.status_code, 200)

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
        analyze_response = self.client.post(
            "/api/meetings/analyze",
            headers=owner_headers,
            json={"transcript": SAMPLE_TRANSCRIPT},
        )
        meeting_id = analyze_response.json()["id"]

        response = self.client.get(f"/api/meetings/{meeting_id}", headers=other_headers)

        self.assertEqual(response.status_code, 404)

    def test_api_transcribes_uploaded_audio(self):
        headers = self.auth_headers()
        original_transcribe = api_module.transcribe_audio
        api_module.transcribe_audio = lambda uploaded_file, filename: f"Transcript from {filename}"
        try:
            response = self.client.post(
                "/api/meetings/transcribe",
                headers=headers,
                files={"file": ("meeting.mp3", b"sample audio bytes", "audio/mpeg")},
            )
        finally:
            api_module.transcribe_audio = original_transcribe

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["transcript"], "Transcript from meeting.mp3")


if __name__ == "__main__":
    unittest.main()

