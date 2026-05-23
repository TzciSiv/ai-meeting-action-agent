import json
import logging
import os
import threading
import time
import uuid
from collections import defaultdict
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator


START_TIME = time.monotonic()
SENSITIVE_FIELD_NAMES = ("authorization", "content", "key", "password", "secret", "source", "token", "transcript")
SAFE_FIELD_NAMES = {"source_type"}

_LOCK = threading.Lock()
_COUNTERS: defaultdict[str, int] = defaultdict(int)
_LATENCIES: defaultdict[str, dict[str, float | int]] = defaultdict(
    lambda: {"count": 0, "total_seconds": 0.0, "max_seconds": 0.0, "latest_seconds": 0.0}
)
_REQUEST_ID: ContextVar[str] = ContextVar("request_id", default="")

try:  # Optional until requirements are installed.
    from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

    _PROMETHEUS_AVAILABLE = True
    _EVENT_COUNTER = Counter("meeting_agent_events_total", "Application event counters.", ["name"])
    _OPERATION_SECONDS = Histogram(
        "meeting_agent_operation_seconds",
        "Operation latency in seconds.",
        ["operation"],
        buckets=(0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, float("inf")),
    )
    _HTTP_REQUESTS = Counter("meeting_agent_http_requests_total", "HTTP requests.", ["method", "path", "status"])
    _HTTP_SECONDS = Histogram(
        "meeting_agent_http_request_seconds",
        "HTTP request latency in seconds.",
        ["method", "path", "status"],
        buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, float("inf")),
    )
except Exception:  # pragma: no cover - exercised only when optional packages are absent
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"
    _PROMETHEUS_AVAILABLE = False
    _EVENT_COUNTER = None
    _OPERATION_SECONDS = None
    _HTTP_REQUESTS = None
    _HTTP_SECONDS = None

try:  # Optional until requirements are installed.
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    _OTEL_AVAILABLE = True
except Exception:  # pragma: no cover - exercised only when optional packages are absent
    trace = None
    OTLPSpanExporter = None
    FastAPIInstrumentor = None
    SQLAlchemyInstrumentor = None
    Resource = None
    TracerProvider = None
    BatchSpanProcessor = None
    _OTEL_AVAILABLE = False

_OTEL_CONFIGURED = False


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            payload.update(fields)
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def sanitize_fields(fields: dict[str, Any]) -> dict[str, Any]:
    sanitized = {}
    for key, value in fields.items():
        lowered = key.lower()
        if lowered in SAFE_FIELD_NAMES:
            sanitized[key] = value if isinstance(value, (str, int, float, bool)) or value is None else str(value)
        elif any(sensitive in lowered for sensitive in SENSITIVE_FIELD_NAMES):
            sanitized[key] = "[redacted]"
        elif isinstance(value, (str, int, float, bool)) or value is None:
            sanitized[key] = value
        else:
            sanitized[key] = str(value)
    return sanitized


def get_logger() -> logging.Logger:
    logger = logging.getLogger("meeting_agent")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonLogFormatter())
        logger.addHandler(handler)
    logger.setLevel(os.getenv("APP_LOG_LEVEL", "INFO").upper())
    logger.propagate = False
    return logger


def log_event(level: int, event: str, **fields: Any) -> None:
    request_id = get_request_id()
    if request_id and "request_id" not in fields:
        fields["request_id"] = request_id
    get_logger().log(level, event, extra={"fields": sanitize_fields(fields)})


def increment_counter(name: str, amount: int = 1) -> None:
    with _LOCK:
        _COUNTERS[name] += amount
    if _EVENT_COUNTER is not None:
        _EVENT_COUNTER.labels(name=name).inc(amount)


def record_latency(name: str, seconds: float) -> None:
    seconds = max(float(seconds), 0.0)
    with _LOCK:
        metric = _LATENCIES[name]
        metric["count"] = int(metric["count"]) + 1
        metric["total_seconds"] = float(metric["total_seconds"]) + seconds
        metric["latest_seconds"] = seconds
        metric["max_seconds"] = max(float(metric["max_seconds"]), seconds)
    if _OPERATION_SECONDS is not None:
        _OPERATION_SECONDS.labels(operation=name).observe(seconds)


def get_request_id() -> str:
    return _REQUEST_ID.get()


def set_request_id(request_id: str) -> None:
    _REQUEST_ID.set(request_id)


def new_request_id() -> str:
    return uuid.uuid4().hex


def _span_attributes(fields: dict[str, Any]) -> dict[str, str | int | float | bool]:
    attributes: dict[str, str | int | float | bool] = {}
    for key, value in sanitize_fields(fields).items():
        if isinstance(value, (str, int, float, bool)):
            attributes[key] = value
    request_id = get_request_id()
    if request_id:
        attributes["request_id"] = request_id
    return attributes


@contextmanager
def trace_span(name: str, **attributes: Any) -> Iterator[None]:
    if trace is None:
        yield
        return

    tracer = trace.get_tracer("meeting_agent")
    with tracer.start_as_current_span(name) as span:
        for key, value in _span_attributes(attributes).items():
            span.set_attribute(key, value)
        yield


@contextmanager
def timed_operation(
    name: str,
    success_counter: str | None = None,
    failure_counter: str | None = None,
    **log_fields: Any,
) -> Iterator[None]:
    start = time.perf_counter()
    try:
        with trace_span(name, operation=name, **log_fields):
            yield
    except Exception as exc:
        elapsed = time.perf_counter() - start
        record_latency(name, elapsed)
        if failure_counter:
            increment_counter(failure_counter)
        log_event(
            logging.ERROR,
            "operation_failed",
            operation=name,
            error_type=type(exc).__name__,
            elapsed_seconds=round(elapsed, 4),
            **log_fields,
        )
        raise
    else:
        elapsed = time.perf_counter() - start
        record_latency(name, elapsed)
        if success_counter:
            increment_counter(success_counter)
        log_event(logging.INFO, "operation_completed", operation=name, elapsed_seconds=round(elapsed, 4), **log_fields)


def local_sla_targets() -> dict[str, Any]:
    return {
        "scope": "production_style_objectives",
        "analysis_average_seconds": float(os.getenv("SLA_ANALYSIS_AVERAGE_SECONDS", "30")),
        "analysis_max_seconds": float(os.getenv("SLA_ANALYSIS_MAX_SECONDS", "120")),
        "error_rate_objective": os.getenv("SLA_ERROR_RATE_OBJECTIVE", "below 5% in local/demo runs"),
        "health_endpoint": "/api/health returns status=ok when the backend is ready",
    }


def metrics_snapshot() -> dict[str, Any]:
    with _LOCK:
        counters = dict(_COUNTERS)
        latencies = {}
        for name, metric in _LATENCIES.items():
            count = int(metric["count"])
            total = float(metric["total_seconds"])
            latencies[name] = {
                "count": count,
                "average_seconds": total / count if count else 0.0,
                "max_seconds": float(metric["max_seconds"]),
                "latest_seconds": float(metric["latest_seconds"]),
            }

    return {
        "uptime_seconds": time.monotonic() - START_TIME,
        "counters": counters,
        "latencies": latencies,
        "sla_targets": local_sla_targets(),
        "integrations": {
            "prometheus": {
                "enabled": os.getenv("PROMETHEUS_METRICS_ENABLED", "true").lower() == "true",
                "available": _PROMETHEUS_AVAILABLE,
                "endpoint": "/metrics",
            },
            "opentelemetry": {
                "enabled": os.getenv("OTEL_TRACES_ENABLED", "true").lower() == "true",
                "available": _OTEL_AVAILABLE,
                "service_name": os.getenv("OTEL_SERVICE_NAME", "ai-meeting-action-agent"),
                "otlp_endpoint": os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", ""),
            },
        },
        "models": {
            "transcription": os.getenv("OPENAI_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe"),
            "summary": os.getenv("OPENAI_SUMMARY_MODEL", "gpt-5-mini"),
            "embedding": os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"),
        },
    }


def _prometheus_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _manual_prometheus_metrics() -> bytes:
    snapshot = metrics_snapshot()
    lines = [
        "# HELP meeting_agent_uptime_seconds Backend process uptime in seconds.",
        "# TYPE meeting_agent_uptime_seconds gauge",
        f"meeting_agent_uptime_seconds {snapshot['uptime_seconds']}",
        "# HELP meeting_agent_events_total Application event counters.",
        "# TYPE meeting_agent_events_total counter",
    ]
    for name, count in snapshot["counters"].items():
        lines.append(f'meeting_agent_events_total{{name="{_prometheus_escape(name)}"}} {count}')

    lines.extend(
        [
            "# HELP meeting_agent_operation_seconds Operation latency summary.",
            "# TYPE meeting_agent_operation_seconds summary",
        ]
    )
    with _LOCK:
        latencies = dict(_LATENCIES)
    for name, metric in latencies.items():
        operation = _prometheus_escape(name)
        lines.append(f'meeting_agent_operation_seconds_count{{operation="{operation}"}} {metric["count"]}')
        lines.append(f'meeting_agent_operation_seconds_sum{{operation="{operation}"}} {metric["total_seconds"]}')
        lines.append(f'meeting_agent_operation_seconds_max{{operation="{operation}"}} {metric["max_seconds"]}')
    return ("\n".join(lines) + "\n").encode("utf-8")


def prometheus_metrics() -> tuple[bytes, str]:
    if os.getenv("PROMETHEUS_METRICS_ENABLED", "true").lower() != "true":
        return b"# Prometheus metrics disabled\n", CONTENT_TYPE_LATEST
    if _PROMETHEUS_AVAILABLE:
        return generate_latest(), CONTENT_TYPE_LATEST
    return _manual_prometheus_metrics(), CONTENT_TYPE_LATEST


def record_http_request(method: str, path: str, status_code: int, elapsed_seconds: float) -> None:
    status = str(status_code)
    increment_counter("http.requests")
    increment_counter(f"http.{method.lower()}.{status}.requests")
    record_latency(f"http.{method.lower()}.{path}", elapsed_seconds)
    if _HTTP_REQUESTS is not None:
        _HTTP_REQUESTS.labels(method=method, path=path, status=status).inc()
    if _HTTP_SECONDS is not None:
        _HTTP_SECONDS.labels(method=method, path=path, status=status).observe(max(elapsed_seconds, 0.0))


def configure_opentelemetry(app: Any, engine: Any | None = None) -> None:
    global _OTEL_CONFIGURED
    if _OTEL_CONFIGURED or not _OTEL_AVAILABLE or os.getenv("OTEL_TRACES_ENABLED", "true").lower() != "true":
        return

    resource = Resource.create({"service.name": os.getenv("OTEL_SERVICE_NAME", "ai-meeting-action-agent")})
    provider = TracerProvider(resource=resource)
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if endpoint and OTLPSpanExporter is not None and BatchSpanProcessor is not None:
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)

    if FastAPIInstrumentor is not None:
        FastAPIInstrumentor.instrument_app(app)
    if engine is not None and SQLAlchemyInstrumentor is not None:
        SQLAlchemyInstrumentor().instrument(engine=engine)
    _OTEL_CONFIGURED = True


def reset_metrics() -> None:
    with _LOCK:
        _COUNTERS.clear()
        _LATENCIES.clear()
