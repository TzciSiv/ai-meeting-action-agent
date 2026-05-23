import argparse
import json
import logging
import os
import socket
import threading
import time
from typing import Any

from .database import SessionLocal, init_db
from .events import TOPIC_ANALYSIS_REQUESTED, TOPIC_MEETING_UPLOADED, TOPIC_TRANSCRIPTION_REQUESTED, publish_pending_outbox
from .governance import sync_prompt_registry
from .observability import increment_counter, log_event
from .pipeline import (
    process_event_envelope,
    process_outbox_once,
    process_stale_queued_jobs_once,
    record_worker_heartbeat,
)


WORKER_TOPICS = (TOPIC_MEETING_UPLOADED, TOPIC_TRANSCRIPTION_REQUESTED, TOPIC_ANALYSIS_REQUESTED)
WORKER_HOSTNAME = socket.gethostname()
WORKER_LABEL = os.getenv("WORKER_NAME", "backend-worker")
WORKER_ID = os.getenv("WORKER_ID") or f"{WORKER_LABEL}:{WORKER_HOSTNAME}"


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


HEARTBEAT_INTERVAL_SECONDS = max(_float_env("WORKER_HEARTBEAT_INTERVAL_SECONDS", 30.0), 1.0)
KAFKA_POLL_TIMEOUT_MS = max(int(_float_env("WORKER_KAFKA_POLL_TIMEOUT_MS", 1000.0)), 100)
QUEUE_RECOVERY_INTERVAL_SECONDS = max(_float_env("WORKER_QUEUE_RECOVERY_INTERVAL_SECONDS", 2.0), 0.5)

_heartbeat_lock = threading.Lock()
_queue_drain_lock = threading.Lock()
_heartbeat_stop = threading.Event()
_heartbeat_thread: threading.Thread | None = None
_heartbeat_state: dict[str, Any] = {
    "mode": "startup",
    "status": "starting",
    "current_topic": "",
    "current_job_id": "",
    "current_event_type": "",
    "last_error": "",
    "processed_delta": 0,
    "failed_delta": 0,
}


def _update_heartbeat_state(
    mode: str,
    status: str,
    current_topic: str = "",
    current_job_id: str = "",
    current_event_type: str = "",
    last_error: str = "",
    processed_delta: int = 0,
    failed_delta: int = 0,
) -> None:
    with _heartbeat_lock:
        _heartbeat_state["mode"] = mode
        _heartbeat_state["status"] = status
        _heartbeat_state["current_topic"] = current_topic
        _heartbeat_state["current_job_id"] = current_job_id
        _heartbeat_state["current_event_type"] = current_event_type
        if last_error:
            _heartbeat_state["last_error"] = last_error[:1000]
        elif status == "processing":
            _heartbeat_state["last_error"] = ""
        _heartbeat_state["processed_delta"] += max(processed_delta, 0)
        _heartbeat_state["failed_delta"] += max(failed_delta, 0)


def _heartbeat_snapshot() -> dict[str, Any]:
    with _heartbeat_lock:
        snapshot = dict(_heartbeat_state)
        _heartbeat_state["processed_delta"] = 0
        _heartbeat_state["failed_delta"] = 0
    return snapshot


def _heartbeat_status() -> str:
    with _heartbeat_lock:
        return str(_heartbeat_state["status"])


def _restore_failed_heartbeat_deltas(snapshot: dict[str, Any]) -> None:
    with _heartbeat_lock:
        _heartbeat_state["processed_delta"] += max(int(snapshot.get("processed_delta") or 0), 0)
        _heartbeat_state["failed_delta"] += max(int(snapshot.get("failed_delta") or 0), 0)


def heartbeat(
    mode: str,
    status: str,
    current_topic: str = "",
    current_job_id: str = "",
    current_event_type: str = "",
    last_error: str = "",
    processed_delta: int = 0,
    failed_delta: int = 0,
) -> None:
    _update_heartbeat_state(
        mode,
        status,
        current_topic=current_topic,
        current_job_id=current_job_id,
        current_event_type=current_event_type,
        last_error=last_error,
        processed_delta=processed_delta,
        failed_delta=failed_delta,
    )
    flush_heartbeat()


def flush_heartbeat() -> None:
    snapshot = _heartbeat_snapshot()
    db = SessionLocal()
    try:
        record_worker_heartbeat(
            db,
            worker_id=WORKER_ID,
            display_name=f"{WORKER_LABEL} {WORKER_HOSTNAME[:12]}",
            hostname=WORKER_HOSTNAME,
            mode=str(snapshot["mode"]),
            status=str(snapshot["status"]),
            current_topic=str(snapshot["current_topic"]),
            current_job_id=str(snapshot["current_job_id"]),
            current_event_type=str(snapshot["current_event_type"]),
            last_error=str(snapshot["last_error"]),
            processed_delta=int(snapshot["processed_delta"]),
            failed_delta=int(snapshot["failed_delta"]),
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        _restore_failed_heartbeat_deltas(snapshot)
        log_event(
            logging.WARNING,
            "worker_heartbeat_failed",
            worker_id=WORKER_ID,
            error_type=type(exc).__name__,
            error_message=str(exc)[:300],
        )
    finally:
        db.close()


def start_heartbeat_loop() -> None:
    global _heartbeat_thread
    if _heartbeat_thread is not None and _heartbeat_thread.is_alive():
        return

    def loop() -> None:
        while not _heartbeat_stop.wait(HEARTBEAT_INTERVAL_SECONDS):
            flush_heartbeat()

    flush_heartbeat()
    _heartbeat_thread = threading.Thread(target=loop, name="worker-heartbeat", daemon=True)
    _heartbeat_thread.start()


def process_envelope(envelope: dict) -> None:
    db = SessionLocal()
    try:
        process_event_envelope(db, envelope)
        publish_pending_outbox(db)
        increment_counter("worker.events.processed")
    except Exception as exc:
        db.rollback()
        increment_counter("worker.events.failed")
        log_event(logging.ERROR, "worker_event_failed", error_type=type(exc).__name__)
        raise
    finally:
        db.close()


def drain_idle_queue_work() -> int:
    if not _queue_drain_lock.acquire(blocking=False):
        return 0
    db = SessionLocal()
    try:
        publish_pending_outbox(db, limit=25)
        recovered = process_stale_queued_jobs_once(db)
        if recovered:
            publish_pending_outbox(db, limit=25)
            heartbeat("kafka", "idle", current_topic="event_outbox", current_event_type="queued_recovery", processed_delta=recovered)
        return recovered
    except Exception as exc:
        db.rollback()
        heartbeat("kafka", "idle", last_error=str(exc), failed_delta=1)
        log_event(logging.WARNING, "worker_idle_queue_drain_failed", error_type=type(exc).__name__)
        return 0
    finally:
        db.close()
        _queue_drain_lock.release()


def start_queue_recovery_loop() -> None:
    def loop() -> None:
        while True:
            time.sleep(QUEUE_RECOVERY_INTERVAL_SECONDS)
            if _heartbeat_status() == "idle":
                drain_idle_queue_work()

    threading.Thread(target=loop, name="worker-queue-recovery", daemon=True).start()


def run_kafka_worker() -> None:
    bootstrap_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    group_id = os.getenv("KAFKA_WORKER_GROUP_ID", "meeting-agent-worker")
    from kafka import KafkaConsumer

    heartbeat("kafka", "starting")
    consumer = KafkaConsumer(
        *WORKER_TOPICS,
        bootstrap_servers=bootstrap_servers,
        group_id=group_id,
        value_deserializer=lambda value: json.loads(value.decode("utf-8")),
        enable_auto_commit=True,
        auto_offset_reset=os.getenv("KAFKA_AUTO_OFFSET_RESET", "earliest"),
    )
    log_event(logging.INFO, "worker_started", mode="kafka", topics=",".join(WORKER_TOPICS))
    heartbeat("kafka", "idle")
    while True:
        records = consumer.poll(timeout_ms=KAFKA_POLL_TIMEOUT_MS)
        if not records:
            _update_heartbeat_state("kafka", "idle")
            drain_idle_queue_work()
            continue
        for messages in records.values():
            for message in messages:
                envelope = message.value
                heartbeat(
                    "kafka",
                    "processing",
                    current_topic=message.topic,
                    current_job_id=str(envelope.get("job_id") or ""),
                    current_event_type=str(envelope.get("event_type") or ""),
                )
                try:
                    process_envelope(envelope)
                except Exception as exc:
                    heartbeat("kafka", "idle", last_error=str(exc), failed_delta=1)
                    log_event(logging.ERROR, "worker_message_skipped", error_type=type(exc).__name__)
                else:
                    heartbeat("kafka", "idle", processed_delta=1)


def run_outbox_poll_worker(interval_seconds: float = 2.0) -> None:
    log_event(logging.INFO, "worker_started", mode="outbox_poll")
    heartbeat("outbox_poll", "idle")
    while True:
        db = SessionLocal()
        try:
            heartbeat("outbox_poll", "processing", current_topic="event_outbox")
            processed = process_outbox_once(db)
            publish_pending_outbox(db)
            if processed:
                increment_counter("worker.outbox.processed", processed)
            heartbeat("outbox_poll", "idle", processed_delta=processed)
        except Exception as exc:
            db.rollback()
            increment_counter("worker.outbox.failed")
            heartbeat("outbox_poll", "idle", last_error=str(exc), failed_delta=1)
            log_event(logging.ERROR, "worker_outbox_batch_failed", error_type=type(exc).__name__)
        finally:
            db.close()
        time.sleep(interval_seconds)


def main() -> int:
    parser = argparse.ArgumentParser(description="Async meeting analysis worker.")
    parser.add_argument("--outbox-once", action="store_true", help="Process one batch of outbox events and exit.")
    parser.add_argument("--outbox-poll", action="store_true", help="Poll the DB outbox instead of Kafka.")
    args = parser.parse_args()

    init_db()
    db = SessionLocal()
    try:
        sync_prompt_registry(db)
    finally:
        db.close()
    heartbeat("startup", "starting")
    start_heartbeat_loop()
    start_queue_recovery_loop()

    if args.outbox_once:
        db = SessionLocal()
        try:
            processed = process_outbox_once(db)
            publish_pending_outbox(db)
            print(f"processed={processed}")
        finally:
            db.close()
        return 0

    if args.outbox_poll or os.getenv("WORKER_MODE", "kafka") == "outbox_poll":
        run_outbox_poll_worker()
        return 0

    try:
        run_kafka_worker()
    except Exception as exc:
        heartbeat("kafka", "error", last_error=str(exc), failed_delta=1)
        log_event(logging.ERROR, "worker_kafka_unavailable", error_type=type(exc).__name__)
        if os.getenv("WORKER_FALLBACK_TO_OUTBOX", "true").lower() == "true":
            run_outbox_poll_worker()
            return 0
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
