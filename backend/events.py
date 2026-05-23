import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import EventOutbox
from .observability import increment_counter, log_event, sanitize_fields


EVENT_VERSION = "1"
TOPIC_MEETING_UPLOADED = "meeting.uploaded"
TOPIC_TRANSCRIPTION_REQUESTED = "transcription.requested"
TOPIC_TRANSCRIPT_TRANSCRIBED = "transcript.transcribed"
TOPIC_TRANSCRIPTION_FAILED = "transcription.failed"
TOPIC_ANALYSIS_REQUESTED = "analysis.requested"
TOPIC_EMBEDDINGS_CREATED = "embeddings.created"
TOPIC_ANALYSIS_COMPLETED = "analysis.completed"
TOPIC_ANALYSIS_FAILED = "analysis.failed"
TOPIC_ACTION_UPDATED = "action.updated"

ALL_TOPICS = (
    TOPIC_MEETING_UPLOADED,
    TOPIC_TRANSCRIPTION_REQUESTED,
    TOPIC_TRANSCRIPT_TRANSCRIBED,
    TOPIC_TRANSCRIPTION_FAILED,
    TOPIC_ANALYSIS_REQUESTED,
    TOPIC_EMBEDDINGS_CREATED,
    TOPIC_ANALYSIS_COMPLETED,
    TOPIC_ANALYSIS_FAILED,
    TOPIC_ACTION_UPDATED,
)

SENSITIVE_EVENT_KEYS = {
    "authorization",
    "content",
    "jwt",
    "key",
    "password",
    "prompt",
    "secret",
    "source_uri",
    "token",
    "transcript",
}


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sanitize_event_payload(payload: dict[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key, value in payload.items():
        lowered = key.lower()
        if any(sensitive in lowered for sensitive in SENSITIVE_EVENT_KEYS):
            sanitized[key] = "[redacted]"
        elif isinstance(value, dict):
            sanitized[key] = sanitize_event_payload(value)
        elif isinstance(value, list):
            sanitized[key] = [
                sanitize_event_payload(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            sanitized[key] = value
    return sanitize_fields(sanitized)


def build_event_envelope(
    event_type: str,
    actor_user_id: int | None = None,
    correlation_id: str | None = None,
    job_id: str | None = None,
    meeting_id: int | None = None,
    resource_type: str = "",
    resource_id: int | str | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "event_id": uuid.uuid4().hex,
        "event_type": event_type,
        "event_version": EVENT_VERSION,
        "occurred_at": utc_iso(),
        "actor_user_id": actor_user_id,
        "correlation_id": correlation_id or job_id or uuid.uuid4().hex,
        "job_id": job_id,
        "meeting_id": meeting_id,
        "resource_type": resource_type,
        "resource_id": None if resource_id is None else str(resource_id),
        "payload": sanitize_event_payload(payload or {}),
    }


def enqueue_event(
    db: Session,
    event_type: str,
    actor_user_id: int | None = None,
    job_id: str | None = None,
    meeting_id: int | None = None,
    resource_type: str = "",
    resource_id: int | str | None = None,
    payload: dict[str, Any] | None = None,
    correlation_id: str | None = None,
    topic: str | None = None,
    key: str | None = None,
) -> EventOutbox:
    topic = topic or event_type
    envelope = build_event_envelope(
        event_type=event_type,
        actor_user_id=actor_user_id,
        correlation_id=correlation_id,
        job_id=job_id,
        meeting_id=meeting_id,
        resource_type=resource_type,
        resource_id=resource_id,
        payload=payload,
    )
    event = EventOutbox(
        event_id=envelope["event_id"],
        topic=topic,
        key=key or str(meeting_id or job_id or envelope["event_id"]),
        event_type=event_type,
        event_version=EVENT_VERSION,
        envelope_json=json.dumps(envelope, ensure_ascii=False, sort_keys=True),
        publish_status="pending",
    )
    db.add(event)
    increment_counter(f"events.{event_type}.queued")
    return event


def event_to_envelope(event: EventOutbox) -> dict[str, Any]:
    try:
        return json.loads(event.envelope_json)
    except json.JSONDecodeError:
        return {}


class KafkaEventPublisher:
    def __init__(self) -> None:
        self.bootstrap_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
        self.enabled = os.getenv("KAFKA_ENABLED", "true").lower() == "true"
        self._producer = None

    def producer(self):
        if not self.enabled:
            return None
        if self._producer is None:
            try:
                from kafka import KafkaProducer
            except Exception as exc:  # pragma: no cover - exercised when dependency is absent
                log_event(logging.WARNING, "kafka_unavailable", error_type=type(exc).__name__)
                self.enabled = False
                return None
            self._producer = KafkaProducer(
                bootstrap_servers=self.bootstrap_servers,
                value_serializer=lambda value: json.dumps(value, ensure_ascii=False).encode("utf-8"),
                key_serializer=lambda value: str(value).encode("utf-8"),
                linger_ms=10,
            )
        return self._producer

    def publish(self, event: EventOutbox) -> None:
        producer = self.producer()
        if producer is None:
            raise RuntimeError("Kafka publisher is unavailable")
        producer.send(event.topic, key=event.key, value=event_to_envelope(event))
        producer.flush(timeout=10)


def publish_pending_outbox(db: Session, limit: int = 100, publisher: KafkaEventPublisher | None = None) -> int:
    publisher = publisher or KafkaEventPublisher()
    events = list(
        db.scalars(
            select(EventOutbox)
            .where(EventOutbox.publish_status.in_(("pending", "failed")))
            .order_by(EventOutbox.created_at.asc(), EventOutbox.id.asc())
            .limit(limit)
        )
    )
    published = 0
    for event in events:
        event.attempts += 1
        try:
            publisher.publish(event)
        except Exception as exc:
            event.publish_status = "failed"
            event.last_error = str(exc)[:1000]
            increment_counter(f"events.{event.event_type}.publish_failed")
        else:
            event.publish_status = "published"
            event.published_at = datetime.now(timezone.utc)
            event.last_error = ""
            published += 1
            increment_counter(f"events.{event.event_type}.published")
    db.commit()
    return published
